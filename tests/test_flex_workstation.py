"""Joint Flex processing and transport, one sequential program and station."""
import json
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from .test_transfer_matrix import TransferMatrixFixture

SOURCE = """// Engineering acceptance: condition a bead suspension and collect its liquid phase.
// Not a validated immunoprecipitation assay or a replacement for Module05.
let prep_plate=plate(label="Preparation",format="96well",capacity=200uL);
let prep=prep_plate[A1];
let magnetic_plate=plate(label="Magnetic",format="96well",capacity=2000uL);
let sample=magnetic_plate[A1];
let stock=tube(label="Stock",capacity=2000uL,load=[content(kind=particulate,type=beads,code="BEADS",attrs={bead_property:magnetic}):10uL,content(kind=formulation,type=buffer,code="BUFFER"):80uL]);
let collection=tube(label="Collection",capacity=2000uL);
prep << [stock];
agit(sample=prep[0],mode=shake,motion=orbital,rate=500rpm,duration=1s);
with env(thermal=37C,duration=1s) { hold(sample=prep); }
sample << [prep[0]];
with env(field=magnetic_rack) {
 hold(sample=sample);
 sep(sample=sample[0],program=magnetic_program(duration=5s));
 collection << [sample[0].contents[1]:40uL];
}
return collection;
"""


class FlexWorkstationFixture:
    def build(self, directory, change=None):
        f=TransferMatrixFixture(); plan=f.compile(SOURCE,directory)
        steps=[s for p in plan.plans for s in p.steps]
        def configure(raw):
            raw.update(robot_type='Flex',pipette='flex_1channel_1000',mount='left',
                tiprack={'load_name':'opentrons_flex_96_tiprack_1000ul','slot':'D3'},
                modules={
                    'shaker':{'model':'heaterShakerModuleV1','slot':'C1','adapter':'opentrons_96_flat_bottom_adapter'},
                    'heater':{'model':'temperature module gen2','slot':'B1'},
                    'magnet':{'model':'magneticBlockV1','slot':'C3','aspirate_height_mm':2,'release_destination':'D2'}},
                labware={'assay':{'load_name':'nest_96_wellplate_200ul_flat','slot':'D1'},
                         'captured':{'load_name':'nest_96_wellplate_2ml_deep','slot':'D2'},
                         'tubes':{'load_name':'opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap','slot':'B2'}})
            raw['bindings']={};tube=well=0
            for step in (s for s in steps if s.op=='AllocContainer'):
                if 'carrier_position' in step.args:
                    address={'labware':('assay','captured')[well],'well':'A1'};well+=1
                else:
                    tube+=1;address={'labware':'tubes','well':f'A{tube}'}
                raw['bindings'][step.step_id]=address
            transfers=[s for s in steps if s.op=='Mutation']
            assert len(transfers)==3
            raw['labware_moves']={
                next(s.step_id for s in steps if s.op=='agit'):[{'labware':'assay','destination':'module:shaker'}],
                next(s.step_id for s in steps if s.op=='env_hold'):[{'labware':'assay','destination':'module:heater'}],
                transfers[1].step_id:[{'labware':'assay','destination':'D1'}],
                next(s.step_id for s in steps if s.op=='sep'):[{'labware':'captured','destination':'module:magnet'}]}
            if change:change(raw,plan)
        context=f.context(directory,plan,config_mutation=configure)
        return plan,context,OSApplicationFactory().build(context)

    def assert_completed(self, app, plan, result):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan,StubDriver(),init_state(plan))
        assert baseline.ok
        assert result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs']==baseline.state.artifacts['protocol_outputs']
        identity=result.user_result['os']['run_id']
        session=app.host.gateway.port.session
        assert session.motion.state['revision']>=5
        assert session.motion.positions()['assay']=='D1'
        assert session.motion.positions()['captured']=='D2'
        assert not session.magnetic.held
        assert not session.backend.module_access.active
        assert not session.backend.temperature_access.active
        assert app.client.lifecycle.reservations.get(identity).status=='released'
        assert not app.client.lifecycle.operations.resource.occupied()
        assert not app.client.lifecycle.operations.motions.motion.repository.pending('opentrons')
        return identity


def test_complete_flex_workstation(tmp_path):
    f=FlexWorkstationFixture();plan,_,app=f.build(tmp_path)
    try:
        result=app.execute(plan,init_state(plan));identity=f.assert_completed(app,plan,result)
        session=app.host.gateway.port.session
        assert len(session.backend.modules)==3
        assert len(session.motion.receipts)==5
        assert session.thermal.receipts[0].payload['module_id']=='heater'
        assert session.agitation.receipts[0].payload['module_id']=='shaker'
        assert session.magnetic.receipts[0].payload['module_id']=='magnet'
        assert app.host.material.get(identity)[2]==6
    finally:app.close()


@pytest.mark.parametrize('location',['heater','shaker'])
@pytest.mark.parametrize('reverse',[False,True])
def test_multiple_modules_choose_docked_capability(tmp_path,location,reverse):
    def change(raw,plan):
        if location=='shaker':
            hold=next(s for p in plan.plans for s in p.steps if s.op=='env_hold')
            raw['labware_moves'].pop(hold.step_id)
        if reverse:raw['modules']=dict(reversed(list(raw['modules'].items())))
    plan,_,app=FlexWorkstationFixture().build(tmp_path,change)
    try:
        result=app.execute(plan,init_state(plan));assert result.ok,result.diagnostics
        assert app.host.gateway.port.session.thermal.receipts[0].payload['module_id']==location
    finally:app.close()


@pytest.mark.parametrize('problem',['missing-magnetic-dock','occupied-slot','wrong-shaker-dock','thermal-off-module'])
def test_incompatible_or_undocked_route_rejects_before_actions(tmp_path,problem):
    def change(raw,plan):
        steps=[s for p in plan.plans for s in p.steps]
        shake=next(s.step_id for s in steps if s.op=='agit')
        heat=next(s.step_id for s in steps if s.op=='env_hold')
        sep=next(s.step_id for s in steps if s.op=='sep')
        if problem=='missing-magnetic-dock':raw['labware_moves'].pop(sep)
        if problem=='occupied-slot':raw['labware_moves'][heat][0]['destination']='B2'
        if problem=='wrong-shaker-dock':raw['labware_moves'][shake][0]['destination']='module:heater'
        if problem=='thermal-off-module':
            raw['labware_moves'][heat][0]['destination']='D1'
            transfer=[s for s in steps if s.op=='Mutation'][1]
            raw['labware_moves'].pop(transfer.step_id)
    plan,_,app=FlexWorkstationFixture().build(tmp_path,change)
    try:
        result=app.execute(plan,init_state(plan));assert not result.ok
        assert result.user_result['os']['preflight']['status']=='rejected'
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:app.close()


class WorkstationDeviceFault:
    def __init__(self, original, hit, after):
        self.original,self.hit,self.after=original,hit,after
        self.calls=0

    def __call__(self,*args,**kwargs):
        self.calls+=1
        if self.calls==self.hit:
            if self.after:self.original(*args,**kwargs)
            raise TimeoutError('joint workstation completion unknown')
        return self.original(*args,**kwargs)


@pytest.mark.parametrize('stage',['latch','shake-stop','handoff','temperature-stop','magnetic-wait','flowthrough','removal'])
@pytest.mark.parametrize('after',[False,True])
def test_unknown_stage_keeps_station_isolated(tmp_path,monkeypatch,stage,after):
    plan,context,app=FlexWorkstationFixture().build(tmp_path)
    session=app.host.gateway.port.session;backend=session.backend
    owner,method,hit={
        'latch':(backend.modules['shaker'],'close_labware_latch',1),
        'shake-stop':(backend.modules['shaker'],'deactivate_shaker',1),
        'handoff':(backend.protocol,'move_labware',2),
        'temperature-stop':(backend.modules['heater'],'deactivate',1),
        'magnetic-wait':(backend.protocol,'delay',3),
        'flowthrough':(backend.pipette,'aspirate',3),
        'removal':(backend.protocol,'move_labware',5)}[stage]
    fault=WorkstationDeviceFault(getattr(owner,method),hit,after)
    monkeypatch.setattr(owner,method,fault)
    try:
        result=app.execute(plan,init_state(plan));assert not result.ok
        identity=result.user_result['os']['run_id']
        assert app.client.get_run(identity).status=='needs_reconciliation'
        assert app.client.lifecycle.reservations.get(identity).status=='active'
        assert app.client.lifecycle.operations.resource.occupied()
        assert fault.calls==hit
        assert app.host.material.get(identity)[2]=={'latch':1,'shake-stop':1,'handoff':2,'temperature-stop':2,'magnetic-wait':4,'flowthrough':5,'removal':6}[stage]
        assert len(session.motion.receipts)==({'latch':1,'shake-stop':1,'handoff':2,'temperature-stop':2,
                                             'magnetic-wait':4,'flowthrough':4,'removal':5}[stage])
    finally:app.close()
    restarted=OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity);restarted.client.start()
        assert restarted.client.run_until_settled(identity).status=='needs_reconciliation'
        assert restarted.client.lifecycle.reservations.get(identity).status=='active'
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
    finally:restarted.close()


def test_completed_move_registration_recovers_without_replay(tmp_path,monkeypatch):
    f=FlexWorkstationFixture();plan,context,app=f.build(tmp_path)
    motion=app.client.lifecycle.operations.motions.motion
    original=motion.register
    def crash(attempt,evidence):
        if attempt.context['description']['motion_intent']['destination']=='module:heater':
            raise KeyboardInterrupt('after handoff receipt before station registration')
        return original(attempt,evidence)
    monkeypatch.setattr(motion,'register',crash)
    try:
        with pytest.raises(KeyboardInterrupt):app.execute(plan,init_state(plan))
        identity=next(iter(app.client.lifecycle.runs.session_runs))
    finally:app.close()
    restarted=OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity);restarted.client.start()
        assert restarted.client.run_until_settled(identity).status=='completed'
        result=restarted.client.result(identity);f.assert_completed(restarted,plan,result)
        commands=restarted.host.gateway.port.session.backend.protocol.commands()
        assert not any('Shake at' in c for c in commands)
        assert len(restarted.host.gateway.port.session.motion.receipts)==3
    finally:restarted.close()


def test_flex_workstation_resident_fifo(tmp_path):
    import sqlite3
    from culsma_os.lifecycle_manager.models import ResidentHostSettings
    from culsma_os.resource_manager.interactors import StationPathInteractor
    from .test_resident_host import ResidentHarness
    from .test_resident_docking import ObservedMotionFactory
    _,context,app=FlexWorkstationFixture().build(tmp_path);app.close()
    probe=ObservedMotionFactory(gate_kind='PreparedOrbitalShake')
    class WorkstationHarness(ResidentHarness):
        def serve(self):
            try:
                self.host=OSApplicationFactory({'opentrons-simulator':probe}).build_resident_host(self.settings)
                self.host.serve()
            except BaseException as error:self.errors.append(error)
    harness=WorkstationHarness(tmp_path,probe);harness.context=context
    harness.settings=ResidentHostSettings(context,harness.endpoint,0.01)
    try:
        harness.start()
        first=harness.client.execute({'action':'submit','source':str(tmp_path/'protocol.culs')})['run_id']
        assert probe.entered.wait(10)
        second=harness.client.execute({'action':'submit','source':str(tmp_path/'protocol.culs')})['run_id']
        assert harness.status(second)['status']=='ready'
        with sqlite3.connect(context.database_path) as connection:
            attempts=[json.loads(r[0]) for r in connection.execute('SELECT record FROM os_attempts')]
            assert not any(a['run_id']==second for a in attempts)
        probe.release.set()
        for identity in (first,second):harness.wait(lambda:harness.status(identity)['status']=='completed',timeout=20)
        with sqlite3.connect(StationPathInteractor().database_path(context)) as connection:
            revision,positions=connection.execute('SELECT revision,positions FROM os_labware_positions').fetchone()
            assert revision==10 and json.loads(positions)['assay']=='D1' and json.loads(positions)['captured']=='D2'
            assert connection.execute('SELECT COUNT(*) FROM os_motion_registrations').fetchone()[0]==10
        assert probe.ports[0].session.backend.available_tips()==90
        for identity in (first,second):
            assert harness.status(identity)['result']['os']['registered_material']['version']==6
        with sqlite3.connect(context.database_path) as connection:
            owners={json.loads(row[0])['attempt_id']:json.loads(row[0])['run_id'] for row in connection.execute('SELECT record FROM os_attempts')}
        assert [owners[d['attempt_id']] for d in probe.dispatches]==[first]*12+[second]*12
    finally:
        probe.release.set();harness.stop()


@pytest.mark.parametrize('entry',['language','os'])
def test_joint_workstation_cli(tmp_path,entry):
    import subprocess,sys
    _,context,app=FlexWorkstationFixture().build(tmp_path);app.close()
    artifacts=tmp_path/'cli-output'
    completed=subprocess.run([sys.executable,'-m','culsma.cli' if entry=='language' else 'culsma_os.cli','run',str(tmp_path/'protocol.culs'),
        '--driver','opentrons-simulator','--driver-config',str(context.config_path),'--artifacts-dir',str(artifacts)],capture_output=True,text=True,timeout=45)
    assert completed.returncode==0,completed.stdout+completed.stderr
    result=json.loads((artifacts/'run.json').read_text())
    assert result['ok'] and result['user_result']['os']['status']=='completed'
    assert result['user_result']['os']['registered_material']['version']==6
