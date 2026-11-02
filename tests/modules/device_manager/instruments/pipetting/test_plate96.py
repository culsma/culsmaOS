from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import pytest
from culsma.runtime.material.args import arg_string
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma.driver.stub import StubDriver
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext, RunRequest
from culsma_os.transfer_engine.models import TransferRequest
from culsma_os.workspace_manager.repository import SqliteSpaceRepository
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER
from tests.support.transfer_engine.plate96 import PlateFixture


class TestPlate96:
    @pytest.mark.parametrize('name,source,expected,addresses',[
        ('tube-well-and-return',PlateFixture.source_text,{'Stock':150,'Assay_A1':30,'Assay_A2':0,'Assay_B1':0,'Assay_B2':20},['A1','B2','A2','A1']),
        ('rectangle',f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); assay[A1:B2] << [stock:20uL];',{'Stock':120,'Assay_A1':20,'Assay_A2':20,'Assay_B1':20,'Assay_B2':20},['A1','A2','B1','B2']),
        ('group-alias',f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); let selected=assay[A1:A2]; let alias=selected; alias[1] << [stock:50uL]; alias[0] << [stock:20uL];',{'Stock':130,'Assay_A1':20,'Assay_A2':50},['A2','A1']),
        ('protocol-return-alias',f'protocol Dose(wells,stock) returns (result) {{ wells[0] << [stock:20uL]; wells[1] << [stock:30uL]; let result=wells; return result; }} let assay=plate(label="Assay",format="96well",capacity=200uL); let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]); let treated=Dose(wells=assay[A1:A2],stock=stock); treated[1] << [stock:20uL];',{'Stock':130,'Assay_A1':20,'Assay_A2':50},['A1','A2','A2']),
        ('two-plates',f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]); let first=plate(label="First",format="96well",carrier_id="P1",capacity=200uL); let second=plate(label="Second",format="96well",carrier_id="P2",capacity=200uL); let a=first[A1]; let b=second[H12]; a << [stock:50uL]; b << [a[0]:20uL];',{'Stock':150,'First_A1':30,'Second_H12':20},['A1','H12']),
        ('whole-liquid',f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); let a=assay[A1]; a << [stock:50uL]; stock << [a[0]];',{'Stock':200,'Assay_A1':0},['A1','A1']),
    ])
    def test_plate_transfer_shapes(self,tmp_path,name,source,expected,addresses,record_property):
        fixture=PlateFixture();plan,context,app=fixture.run_case(tmp_path,source)
        try:
            result=app.execute(plan,init_state(plan))
            fixture.assert_material(result,expected)
            baseline=run(plan,StubDriver(),init_state(plan))
            assert baseline.ok and result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
            backend=app.host.gateway.port.session.backend
            assert backend.protocol.is_simulating()
            commands=[c for r in backend.receipts for c in r.operation.commands]
            assert [c.target_address.well for c in commands]==addresses
            if name=='two-plates':
                assert [c.target_address.labware for c in commands]==['plate1','plate2']
            if name=='tube-well-and-return':
                assert [c.target_address.labware for c in commands]==['plate1','plate1','plate1','tubes']
            assert all(a.status=='returned' for r in backend.receipts for a in r.action_results)
            run_id=result.user_result['os']['run_id']
            space=app.client.lifecycle.operations.space
            snapshot=space.get(run_id)
            plate_bindings=[b for b in snapshot.bindings if b.carrier_id]
            assert plate_bindings and all(b.carrier_position==b.well for b in plate_bindings)
            assert all('container/' in b.reference.container_id for b in plate_bindings)
            assert sum(c['components'].get('BUFFER',0) for c in result.state.artifacts['material_state']['containers'].values())==200
            record_property('coverage',json.dumps({'status':'completed','shape':name,'physical_target_wells':addresses,'strokes':len(commands)}))
        finally:
            app.close()

    def test_all_96_wells(self,tmp_path,record_property):
        fixture=PlateFixture()
        source=f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:1000uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); assay[A1:H12] << [stock:10uL];'
        plan,context,app=fixture.run_case(tmp_path,source,'p20_single_gen2')
        try:
            result=app.execute(plan,init_state(plan))
            assert result.ok,[d.to_dict() for d in result.diagnostics]
            backend=app.host.gateway.port.session.backend
            commands=[c for r in backend.receipts for c in r.operation.commands]
            expected=[f'{row}{column}' for row in 'ABCDEFGH' for column in range(1,13)]
            assert [c.target_address.well for c in commands]==expected
            assert len(commands)==96 and backend.available_tips()==0
            containers=result.state.artifacts['material_state']['containers'].values()
            assert sorted(c['volume_uL'] for c in containers)==[10]*96+[40]
            assert sum(c['components'].get('BUFFER',0) for c in containers)==1000
            assert not app.client.lifecycle.operations.resource.occupied()
            record_property('coverage',json.dumps({'status':'completed','shape':'all_96_wells','physical_target_wells':expected,'strokes':96}))
        finally:
            app.close()

    @pytest.mark.parametrize('problem,code',[
        ('wrong-position','WORKSPACE_WELL_POSITION_MISMATCH'),
        ('wrong-geometry','WORKSPACE_PLATE_GEOMETRY_UNSUPPORTED'),
        ('tiprack-as-plate','WORKSPACE_PLATE_GEOMETRY_UNSUPPORTED'),
        ('missing-binding','WORKSPACE_BINDING_MISSING'),
        ('physical-capacity','WORKSPACE_CAPACITY_MISMATCH'),
        ('carrier-split','WORKSPACE_CARRIER_SPLIT'),
        ('carrier-collision','WORKSPACE_CARRIER_COLLISION'),
    ])
    def test_plate_binding_rejections(self,tmp_path,problem,code,record_property):
        fixture=PlateFixture()
        if problem=='carrier-collision':
            source=f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]); let first=plate(format="96well",carrier_id="P1",capacity=200uL); let second=plate(format="96well",carrier_id="P2",capacity=200uL); let a=first[A1]; let b=second[H12]; a << [stock:50uL]; b << [stock:20uL];'
        else:
            source=PlateFixture.source_text.replace('capacity=200uL','capacity=400uL') if problem=='physical-capacity' else PlateFixture.source_text
        plan=fixture.compile(source,tmp_path)
        context=fixture.context(tmp_path,plan)
        raw=json.loads(context.config_path.read_text())
        keys=[k for k,v in raw['bindings'].items() if v['labware'].startswith('plate')]
        if problem=='wrong-position':raw['bindings'][keys[0]]['well']='H12'
        if problem=='wrong-geometry':raw['labware']['plate1']['load_name']='opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap'
        if problem=='tiprack-as-plate':raw['labware']['plate1']['load_name']='opentrons_96_tiprack_300ul'
        if problem=='missing-binding':del raw['bindings'][keys[0]]
        if problem=='carrier-split':
            raw['labware']['plate2']={'load_name':'corning_96_wellplate_360ul_flat','slot':'4'}
            raw['bindings'][keys[-1]]['labware']='plate2'
        if problem=='carrier-collision':raw['bindings'][keys[-1]]['labware']='plate1'
        context.config_path.write_text(json.dumps(raw))
        app=OSApplicationFactory().build(context)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert code in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
            with sqlite3.connect(context.database_path) as conn:
                assert conn.execute('SELECT count(*) FROM os_attempts').fetchone()[0]==0
            record_property('coverage',json.dumps({'status':'expected_rejection','diagnostic':code}))
        finally:
            app.close()

    @pytest.mark.parametrize('change',['position','geometry','capacity'])
    def test_stale_plate_layout(self,tmp_path,change,monkeypatch,record_property):
        fixture=PlateFixture();plan,context,app=fixture.run_case(tmp_path,PlateFixture.source_text)
        space=app.client.lifecycle.operations.space
        original=space.validate_snapshot
        def invalidate(run_id,revision):
            binding=next(b for b in space.get(run_id).bindings if b.carrier_id)
            if change=='position':
                from culsma_opentrons.models import WellAddress
                space.positions[binding.allocation_step_id]=WellAddress(binding.labware,'H12')
            elif change=='geometry':space.geometries[binding.labware]=(4,6)
            else:space.capacities[binding.labware,binding.well]=1
            return original(run_id,revision)
        monkeypatch.setattr(space,'validate_snapshot',invalidate)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['status']=='failed'
            assert 'STALE' in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert not app.client.lifecycle.operations.resource.occupied()
            record_property('coverage',json.dumps({'status':'expected_rejection','diagnostic':'stale_'+change}))
        finally:app.close()

    def test_plate_restart_without_reexecution(self,tmp_path,record_property):
        fixture=PlateFixture();plan,context,app=fixture.run_case(tmp_path,PlateFixture.source_text)
        try:
            app.client.start();run_id=app.client.submit_run(RunRequest(plan,init_state(plan)))
            app.client.lifecycle.runs.advance_ready(run_id)
            app.client.lifecycle.operations.dispatch_ready(run_id)
            assert len(app.host.gateway.port.session.backend.receipts)==1
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            record=restarted.client.run_until_settled(run_id)
            assert record.status=='completed'
            result=restarted.client.result(run_id)
            fixture.assert_material(result,{'Stock':150,'Assay_A1':30,'Assay_A2':0,'Assay_B1':0,'Assay_B2':20})
            assert len(restarted.host.gateway.port.session.backend.receipts)==3
            assert restarted.host.gateway.port.session.backend.available_tips()==92
            record_property('coverage',json.dumps({'status':'completed','shape':'restart_after_first_step','new_receipts':3}))
        finally:restarted.close()

    def test_plate_failure_blocks_next_step(self,tmp_path,monkeypatch,record_property):
        fixture=PlateFixture();plan,context,app=fixture.run_case(tmp_path,PlateFixture.source_text)
        def fail(*args,**kwargs):raise RuntimeError('injected plate dispense failure')
        monkeypatch.setattr(app.host.gateway.port.session.backend.pipette,'dispense',fail)
        try:
            result=app.execute(plan,init_state(plan));run_id=result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status']=='needs_reconciliation'
            assert [c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values()]==[200,0,0,0,0]
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.host.material.uncertainties(run_id)
            record_property('coverage',json.dumps({'status':'expected_uncertainty','shape':'plate_dispense_failure'}))
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start();restarted.client.run_until_settled(run_id)
            assert restarted.client.get_run(run_id).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally:restarted.close()

    @pytest.mark.parametrize('entry',['language','os'])
    def test_plate_cli(self,tmp_path,entry,record_property):
        fixture=PlateFixture();plan=fixture.compile(PlateFixture.source_text,tmp_path)
        context=fixture.context(tmp_path,plan);artifacts=tmp_path/'cli'
        command=[str(Path(sys.executable).parent/'culsma')] if entry=='language' else [sys.executable,'-m','culsma_os.cli']
        result=subprocess.run([*command,'run',str(tmp_path/'protocol.culs'),'--driver','opentrons-simulator','--driver-config',str(context.config_path),'--artifacts-dir',str(artifacts)],capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        data=json.loads((artifacts/'run.json').read_text())
        assert data['user_result']['os']['status']=='completed'
        assert sum(c['volume_uL'] for c in data['state']['artifacts']['material_state']['containers'].values())==200
        record_property('coverage',json.dumps({'status':'completed','shape':entry+'_cli'}))


    @pytest.mark.parametrize('format,load_name,corner,geometry',[
        ('6well','corning_6_wellplate_16.8ml_flat','B3',(2,3)),
        ('12well','corning_12_wellplate_6.9ml_flat','C4',(3,4)),
        ('24well','corning_24_wellplate_3.4ml_flat','D6',(4,6)),
        ('48well','corning_48_wellplate_1.6ml_flat','F8',(6,8)),
        ('96well','corning_96_wellplate_360ul_flat','H12',(8,12)),
        ('384well','corning_384_wellplate_112ul_flat','P24',(16,24)),
    ])
    def test_parameterized_plate_geometry(self,tmp_path,format,load_name,corner,geometry):
        fixture=PlateFixture()
        source=f'''let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]);
let assay=plate(label="Assay",format="{format}",capacity=100uL);
let a=assay[A1]; let b=assay[{corner}];
a << [stock:40uL]; b << [a[0]:20uL]; stock << [b[0]:20uL];'''
        plan=fixture.compile(source,tmp_path)
        context=fixture.context(tmp_path,plan,config_mutation=lambda c:c['labware']['plate1'].update(load_name=load_name))
        app=OSApplicationFactory().build(context)
        try:
            result=app.execute(plan,init_state(plan))
            assert result.ok,[d.to_dict() for d in result.diagnostics]
            baseline=run(plan,StubDriver(),init_state(plan))
            assert baseline.ok and result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
            backend=app.host.gateway.port.session.backend
            assert backend.protocol.is_simulating()
            commands=[c for r in backend.receipts for c in r.operation.commands]
            assert [c.target_address.well for c in commands]==['A1',corner,'A1']
            snapshot=app.client.lifecycle.operations.space.get(result.user_result['os']['run_id'])
            assert {b.carrier_geometry for b in snapshot.bindings if b.carrier_id}=={geometry}
        finally:app.close()

    @pytest.mark.parametrize('value', [None, {'kind':'IRQuantity','value':0,'unit':None},
        {'kind':'IRQuantity','value':True,'unit':None},
        {'kind':'IRQuantity','value':8.5,'unit':None},
        {'kind':'IRQuantity','value':8,'unit':'mL'},
        {'kind':'IRQuantity','value':'8','unit':None}])
    def test_geometry_metadata_is_required(self,tmp_path,value):
        fixture=PlateFixture();plan=fixture.compile(PlateFixture.source_text,tmp_path)
        for protocol in plan.plans:
            for step in protocol.steps:
                if arg_string(step.args.get('kind'))=='well':
                    if value is None:step.args.pop('carrier_rows')
                    else:step.args['carrier_rows']=value
        context=fixture.context(tmp_path,plan);app=OSApplicationFactory().build(context)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert 'WORKSPACE_PLATE_GEOMETRY_REQUIRED' in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()

    def test_small_selection_does_not_hide_geometry_mismatch(self,tmp_path):
        fixture=PlateFixture()
        source=f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let p=plate(format="24well",capacity=100uL); p[A1] << [stock:20uL];'
        plan,context,app=fixture.run_case(tmp_path,source)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert 'WORKSPACE_PLATE_GEOMETRY_UNSUPPORTED' in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()

    def test_geometry_snapshot_roundtrip_and_staleness(self,tmp_path):
        from culsma_os.workspace_manager.interactors import SpaceInteractor
        from types import SimpleNamespace
        conn=sqlite3.connect(tmp_path/'geometry.sqlite3');repo=SqliteSpaceRepository(conn)
        space=SpaceInteractor(repo,{'alloc':SimpleNamespace(labware='p',well='A1')},{('p','A1'):200},{'p':(4,6)})
        step=SimpleNamespace(op='AllocContainer',step_id='alloc',args={
            'kind':'well','carrier_kind':'plate','carrier_id':'P','container_namespace':'N',
            'carrier_position':'A1','carrier_rows':{'kind':'IRQuantity','value':4,'unit':None},
            'carrier_cols':{'kind':'IRQuantity','value':6,'unit':None}})
        state={'containers':{'container/one':{'metadata':{'kind':'well','allocation_step_id':'alloc','capacity_uL':100}}}}
        try:
            first=space.bind('r',state,(step,))
            assert repo.get('r')==first
            space.validate_snapshot('r',first.revision)
            space.geometries['p']=(8,12)
            with pytest.raises(ValueError,match='WORKSPACE_LAYOUT_STALE'):space.validate_snapshot('r',first.revision)
            step.args['carrier_rows']['value']=8;step.args['carrier_cols']['value']=12
            second=space.bind('r',state,(step,))
            assert first.revision!=second.revision
            data=json.loads(conn.execute('SELECT snapshot FROM os_layouts WHERE run_id=?',('r',)).fetchone()[0])
            data['bindings'][0].pop('carrier_geometry')
            conn.execute('UPDATE os_layouts SET snapshot=? WHERE run_id=?',(json.dumps(data),'r'));conn.commit()
            assert repo.get('r').bindings[0].carrier_geometry is None
            with pytest.raises(ValueError,match='WORKSPACE_LAYOUT_STALE'):space.validate_snapshot('r',second.revision)
        finally:conn.close()

    def test_legacy_tube_layout(self,tmp_path,record_property):
        conn=sqlite3.connect(tmp_path/'legacy.sqlite3');repo=SqliteSpaceRepository(conn)
        data={'run_id':'old','revision':'legacy','bindings':[{'reference':{'container_id':'container/old'},'labware':'tubes','well':'A1','capacity_uL':2000,'allocation_step_id':'alloc'}]}
        conn.execute('INSERT INTO os_layouts VALUES(?,?)',('old',json.dumps(data)));conn.commit()
        try:
            snapshot=repo.get('old')
            assert snapshot.bindings[0].carrier_id is None and snapshot.bindings[0].reference.container_id=='container/old'
            record_property('coverage',json.dumps({'status':'compatibility_pass','shape':'legacy_tube_layout'}))
        finally:conn.close()

    def test_invalid_physical_well_rejected_at_setup(self,tmp_path,monkeypatch,record_property):
        fixture=PlateFixture()
        plan=fixture.compile(PlateFixture.source_text,tmp_path)
        context=fixture.context(tmp_path,plan)
        config=json.loads(context.config_path.read_text())
        key=next(k for k,v in config["bindings"].items() if v["labware"]=="plate1")
        config["bindings"][key]["well"]="Z99"
        context.config_path.write_text(json.dumps(config))
        from culsma_opentrons import backend
        from culsma_opentrons.models import DriverValidationError
        original=backend.get_protocol_api
        observed=[]
        def capture(*args,**kwargs):
            protocol=original(*args,**kwargs)
            observed.append(protocol)
            return protocol
        monkeypatch.setattr(backend,"get_protocol_api",capture)
        with pytest.raises(DriverValidationError) as error:
            OSApplicationFactory().build(context)
        assert error.value.code=="DRV_OT_WELL_UNKNOWN"
        assert observed and not observed[0].commands()
        assert not context.database_path.exists()
        record_property("coverage",json.dumps({"status":"expected_rejection","diagnostic":"DRV_OT_WELL_UNKNOWN"}))

