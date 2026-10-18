"""Transfer conformance through real official API contexts, not fake hardware ports."""
from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from math import ceil, nextafter
from pathlib import Path
import json
import sqlite3
import subprocess
import sys

import pytest
from culsma.driver.stub import StubDriver
from culsma.frontend.resolver import resolve_files
from culsma.pipeline.compile import compile_ast
from culsma.pipeline.entrypoints import resolve_entry
from culsma.pipeline.plan import lower_ir_to_plan
from culsma.pipeline.typecheck import typecheck
from culsma.pipeline.validate import validate
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext

BUFFER = 'content(kind = formulation, type = buffer, code = "BUFFER")'
CELLS = 'content(kind = bio_cellular, type = cell_line, code = "RPE1")'
MEDIUM = 'content(kind = formulation, type = medium, code = "MEDIUM")'
PIPETTES = {'p20_single_gen2': (1, 20, 'opentrons_96_tiprack_20ul'), 'p300_single_gen2': (20, 300, 'opentrons_96_tiprack_300ul')}


@dataclass(frozen=True)
class TransferCase:
    name: str
    body: str
    expected: tuple[float, ...]
    strokes: tuple[float, ...]
    load: str = f'{BUFFER}:200uL'
    declarations: str = ''
    policy: str = 'single'
    pipette: str = 'p300_single_gen2'


SHAPES = (
    TransferCase('whole-liquid', 'target << [source];', (0, 200), (200,)),
    TransferCase('whole-after-partial', 'target << [source:50uL]; target << [source];', (0, 200), (50, 150)),
    TransferCase('whole-split', 'target << [source];', (0, 610), (610/3, 610/3, 610-2*(610/3)), load=f'{BUFFER}:610uL', policy='balanced_split'),
    TransferCase('alias-source', 'let alias = source; target << [alias:50uL];', (150, 50), (50,)),
    TransferCase('alias-target', 'let alias = target; alias << [source:50uL];', (150, 50), (50,)),
    TransferCase('expression', 'target << [source:(100uL + 0.1mL) / 4];', (150, 50), (50,)),
    TransferCase('bound-quantity', 'let total = 0.1mL; let amount = total / 2; target << [source:amount];', (150, 50), (50,)),
    TransferCase('same-source-twice', 'target << [source:50uL, source:75uL];', (75, 125), (50, 75)),
    TransferCase('mixed-whole-and-quantity', 'target << [source:50uL, source];', (0, 200), (50, 150)),
    TransferCase('many-to-one', 'target << [source:50uL, second:100uL];', (150, 150, 100), (50, 100), declarations=f'let second = tube(capacity = 2000uL, load = [{BUFFER}:200uL]);'),
    TransferCase('one-to-many', 'target << [source:50uL]; second << [source:75uL];', (75, 50, 75), (50, 75), declarations='let second = tube(capacity = 2000uL);'),
    TransferCase('serial-dilution', 'target << [source:100uL]; second << [target:100uL];', (100, 200, 300), (100, 100), declarations=f'let second = tube(capacity = 2000uL, load = [{BUFFER}:200uL]);', load=f'{BUFFER}:200uL'),
    TransferCase('round-trip', 'target << [source:50uL]; source << [target:20uL];', (170, 30), (50, 20)),
    TransferCase('cells-explicit-carrier', 'target << [source:25000cells];', (150, 50), (50,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('cells-default-carrier', 'target << [source:25000cells];', (75, 25), (25,), load=f'{CELLS}:100000cells'),
    TransferCase('cells-all', 'target << [source:100000cells];', (0, 200), (200,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('cells-quantity-arithmetic', 'let amount = 100000cells / 4; target << [source:amount];', (150, 50), (50,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('whole-cell-suspension', 'target << [source];', (0, 200), (200,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('volume-cell-suspension', 'target << [source:50uL];', (150, 50), (50,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('near-total-actual-volume', 'target << [source:100uL];', (0, nextafter(100.0, 0)), (nextafter(100.0, 0),), load=f'{BUFFER}:{nextafter(100.0, 0)}uL'),
)


class TransferMatrixFixture:
    def compile(self, source, directory):
        path = directory / 'protocol.culs'
        path.write_text(source)
        compiled = compile_ast(resolve_files([path]).prepared_program)
        checked = validate(compiled.ir, analysis=compiled.analysis, enforce_binding=True)
        typed = typecheck(checked.ir, analysis=compiled.analysis)
        errors = [d for d in [*checked.diagnostics, *typed.diagnostics] if d.severity == 'error']
        assert not errors, [d.to_dict() for d in errors]
        plan = lower_ir_to_plan(typed.ir, analysis=compiled.analysis, entry_resolution=resolve_entry(typed.ir))
        assert not [d for d in plan.diagnostics if d.severity == 'error'], plan.diagnostics
        return plan

    def source(self, body, load=f'{BUFFER}:200uL', declarations='', target_load='', capacity=2000):
        extra = f', load = [{target_load}]' if target_load else ''
        return f'let source = tube(capacity = 2000uL, load = [{load}]); let target = tube(capacity = {capacity}uL{extra}); {declarations}\n{body}'

    def context(self, directory, plan, pipette='p300_single_gen2', policy='single', config_mutation=None):
        allocations = [s for p in plan.plans for s in p.steps if s.op == 'AllocContainer']
        config = {
            'robot_type': 'OT-2', 'api_level': '2.20', 'pipette': pipette, 'mount': 'right',
            'tiprack': {'load_name': PIPETTES[pipette][2], 'slot': '2'},
            'labware': {'tubes': {'load_name': 'opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap', 'slot': '1'}},
            'bindings': {s.step_id: {'labware': 'tubes', 'well': f'{chr(65+i//6)}{i%6+1}'} for i, s in enumerate(allocations)},
            'transfer_policy': {'stroke_mode': policy},
        }
        if config_mutation:
            config_mutation(config)
        path = directory / 'deck.json'
        path.write_text(json.dumps(config))
        return HostBuildContext(directory / 'os.sqlite3', 'opentrons-simulator', path, directory / 'artifacts')

    def volumes(self, result):
        return tuple(c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values())

    def assert_completed(self, app, plan, result, expected, strokes):
        assert result.ok, [d.to_dict() for d in result.diagnostics]
        assert result.user_result['os']['status'] == 'completed'
        assert self.volumes(result) == pytest.approx(expected)
        baseline = run(plan, StubDriver(), init_state(plan))
        assert baseline.ok
        assert result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
        backend = app.host.gateway.port.session.backend
        assert backend.protocol.is_simulating()
        receipts = backend.receipts
        commands = [c for r in receipts for c in r.operation.commands]
        assert [c.volume_uL for c in commands] == pytest.approx(strokes)
        assert all(backend.pipette.min_volume <= c.volume_uL <= backend.pipette.max_volume for c in commands)
        actions = [a for r in receipts for a in r.action_results]
        assert len(actions) == 4 * len(strokes) and all(a.status == 'returned' for a in actions)
        assert len({a.action_id for a in actions}) == len(actions)
        assert backend.available_tips() == 96 - len(strokes)
        assert not app.client.lifecycle.operations.resource.occupied()
        run_id = result.user_result['os']['run_id']
        assert app.host.material.get(run_id)[1] == result.state.artifacts['material_state']
        return {'status': 'completed', 'mode': 'simulation', 'volumes_uL': self.volumes(result), 'strokes_uL': [c.volume_uL for c in commands], 'receipts': len(receipts)}


class TestTransferMatrix:
    @pytest.mark.parametrize('pipette,unit,policy,scale', list(product(PIPETTES, ('uL', 'mL', 'L'), ('single', 'balanced_split'), (0, 1, 2, 3))), ids=lambda v: str(v))
    def test_volume_unit_and_pipette_matrix(self, tmp_path, pipette, unit, policy, scale, record_property):
        minimum, maximum, _ = PIPETTES[pipette]
        volume = (minimum, (minimum+maximum)/2, maximum, maximum*2+minimum)[scale]
        number = volume / {'uL': 1, 'mL': 1000, 'L': 1000000}[unit]
        fixture = TransferMatrixFixture()
        plan = fixture.compile(fixture.source(f'target << [source:{number:.12f}{unit}];', load=f'{BUFFER}:1500uL'), tmp_path)
        app = OSApplicationFactory().build(fixture.context(tmp_path, plan, pipette, policy))
        try:
            result = app.execute(plan, init_state(plan))
            if policy == 'single' and volume > maximum:
                assert not result.ok and result.user_result['os']['status'] == 'failed'
                assert 'DRV_OT_VOLUME_RANGE' in ' '.join(d.message for d in result.diagnostics)
                assert not app.host.gateway.port.session.backend.protocol.commands()
                assert fixture.volumes(result) == (1500, 0)
                record_property('coverage', json.dumps({'status': 'expected_device_rejection', 'volume_uL': volume}))
            else:
                count = ceil(volume / maximum)
                stroke = volume / count
                expected_strokes = (stroke,) * (count-1) + (volume-stroke*(count-1),)
                evidence = fixture.assert_completed(app, plan, result, (1500-volume, volume), expected_strokes)
                record_property('coverage', json.dumps(evidence))
        finally:
            app.close()

    @pytest.mark.parametrize('case', SHAPES, ids=lambda c: c.name)
    def test_transfer_shapes(self, tmp_path, case, record_property):
        fixture = TransferMatrixFixture()
        target_load = f'{BUFFER}:200uL' if case.name == 'serial-dilution' else ''
        plan = fixture.compile(fixture.source(case.body, case.load, case.declarations, target_load), tmp_path)
        app = OSApplicationFactory().build(fixture.context(tmp_path, plan, case.pipette, case.policy))
        try:
            result = app.execute(plan, init_state(plan))
            evidence = fixture.assert_completed(app, plan, result, case.expected, case.strokes)
            if case.name.startswith('cells') or 'cell-suspension' in case.name:
                containers = result.state.artifacts['material_state']['containers'].values()
                assert sum(c['component_quantities'].get('RPE1', {}).get('value', 0) for c in containers) == pytest.approx(100000)
            record_property('coverage', json.dumps(evidence))
        finally:
            app.close()

    def test_cell_count_uses_carrier_volume(self, tmp_path, record_property):
        fixture = TransferMatrixFixture()
        load = f'{CELLS}:100000cells, {MEDIUM}:300uL, content(kind=chemical, type=inorganic_compound, code="SALT"):10mg'
        plan = fixture.compile(fixture.source('target << [source:25000cells];', load), tmp_path)
        app = OSApplicationFactory().build(fixture.context(tmp_path, plan))
        try:
            result = app.execute(plan, init_state(plan))
            evidence = fixture.assert_completed(app, plan, result, (232.5, 77.5), (75,))
            target = list(result.state.artifacts['material_state']['containers'].values())[1]
            assert target['component_quantities']['SALT']['value'] == 2.5
            record_property('coverage', json.dumps(evidence))
        finally:
            app.close()

    @pytest.mark.parametrize('name,body,load,capacity,code', [
        ('insufficient-stock','target << [source:250uL];', f'{BUFFER}:200uL',2000,'MAT_INSUFFICIENT_VOLUME'),
        ('target-capacity','target << [source:100uL];',f'{BUFFER}:200uL',50,'MAT_CONTAINER_OVERFLOW'),
        ('below-pipette-min','target << [source:19uL];',f'{BUFFER}:200uL',2000,'DRV_OT_VOLUME_RANGE'),
        ('negative-volume','target << [source:-1uL];',f'{BUFFER}:200uL',2000,'MAT_UNSUPPORTED_UNIT'),
        ('dry-mass','target << [source:25mg];','content(kind=bio_molecule_or_virus,type=protein,code="P"):100mg',2000,'TRANSFER_LIQUID_VOLUME_REQUIRED'),
        ('whole-dry-mass','target << [source];','content(kind=bio_molecule_or_virus,type=protein,code="P"):100mg',2000,'TRANSFER_LIQUID_VOLUME_REQUIRED'),
        ('whole-mixed-mass','target << [source];',f'{MEDIUM}:300uL, content(kind=chemical,type=inorganic_compound,code="SALT"):10mg',2000,'TRANSFER_LIQUID_VOLUME_REQUIRED'),
        ('gentle','target << [source:50uL] with constraint(gentle);',f'{BUFFER}:200uL',2000,'TRANSFER_CONSTRAINT_UNSUPPORTED'),
        ('dropwise','target << [source:50uL] with constraint(dropwise);',f'{BUFFER}:200uL',2000,'TRANSFER_CONSTRAINT_UNSUPPORTED'),
        ('environment','with env(thermal=37C) { target << [source:50uL]; }',f'{BUFFER}:200uL',2000,'TRANSFER_GATE_UNSUPPORTED'),
        ('physical-capacity','target << [source:50uL];',f'{BUFFER}:200uL',3000,'WORKSPACE_CAPACITY_MISMATCH'),
        ('late-declaration','target << [source:50uL]; let late = tube(capacity=2000uL);',f'{BUFFER}:200uL',2000,'HOST_OPERATION_UNSUPPORTED'),
    ])
    def test_rejection_matrix(self, tmp_path, name, body, load, capacity, code, record_property):
        fixture = TransferMatrixFixture()
        plan = fixture.compile(fixture.source(body, load, capacity=capacity), tmp_path)
        app = OSApplicationFactory().build(fixture.context(tmp_path, plan))
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok
            diagnostic = ' '.join(d.code+' '+d.message for d in result.diagnostics)
            assert code in diagnostic, diagnostic
            assert not app.host.gateway.port.session.backend.protocol.commands()
            with sqlite3.connect(tmp_path/'os.sqlite3') as conn:
                assert conn.execute('SELECT count(*) FROM os_attempts').fetchone()[0] == 0
                assert conn.execute('SELECT count(*) FROM os_material_changes').fetchone()[0] == 0
            record_property('coverage', json.dumps({'status': 'expected_rejection', 'diagnostic': code}))
        finally:
            app.close()


    @pytest.mark.parametrize('body,code', [
        ('target << [source:50%];', 'TYPE_MUTATION_QUANTITY_DIMENSION_MISMATCH'),
        ('let refs = [source, target]; refs[1] << [refs[0]:50uL];', 'SEM_INVALID_GROUP_INDEX_BASE'),
        ('target << [source:50uL] with constraint(spread);', 'SEM_SPREAD_TARGET_NOT_SURFACE'),
        ('target << [missing:50uL];', 'SEM_UNBOUND_NAME_REFERENCE'),
    ])
    def test_language_rejections_before_device(self, tmp_path, body, code, monkeypatch, record_property):
        fixture = TransferMatrixFixture()
        path = tmp_path/'invalid.culs'
        path.write_text(fixture.source(body))
        compiled = compile_ast(resolve_files([path]).prepared_program)
        checked = validate(compiled.ir, analysis=compiled.analysis, enforce_binding=True)
        typed = typecheck(checked.ir, analysis=compiled.analysis)
        diagnostics = [d.code for d in [*checked.diagnostics, *typed.diagnostics] if d.severity == 'error']
        assert code in diagnostics, diagnostics
        assert not checked.ok or not typed.ok
        record_property('coverage',json.dumps({'status':'expected_language_rejection','diagnostic':code}))

    @pytest.mark.parametrize('action,failed_call', [('pick_up_tip',1),('aspirate',1),('dispense',1),('drop_tip',1),('aspirate',2),('dispense',2)])
    def test_device_action_failure_retains_material_and_blocks_resume(self, tmp_path, monkeypatch, action, failed_call, record_property):
        fixture = TransferMatrixFixture()
        plan = fixture.compile(fixture.source('target << [source:610uL]; target << [source:20uL];',f'{BUFFER}:1000uL'),tmp_path)
        context = fixture.context(tmp_path,plan,policy='balanced_split')
        app = OSApplicationFactory().build(context)
        backend = app.host.gateway.port.session.backend
        original = getattr(backend.pipette,action)
        count = 0
        def fail(*args,**kwargs):
            nonlocal count
            count += 1
            if count == failed_call:
                raise RuntimeError('injected simulated interruption')
            return original(*args,**kwargs)
        monkeypatch.setattr(backend.pipette,action,fail)
        try:
            result = app.execute(plan,init_state(plan))
            run_id=result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status']=='needs_reconciliation'
            assert fixture.volumes(result)==(1000,0)
            assert app.client.lifecycle.operations.resource.occupied()
            assert len(app.host.material.uncertainties(run_id))==1
            assert not backend.receipts
            record_property('coverage',json.dumps({'status':'expected_uncertainty','action':action,'failed_call':failed_call}))
        finally:
            app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            restarted.client.run_until_settled(run_id)
            assert restarted.client.get_run(run_id).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.operations.resource.occupied()
        finally:
            restarted.close()

    @pytest.mark.parametrize('entry',['language','os'])
    @pytest.mark.parametrize('body,strokes', [('target << [source];',(200,)),('target << [source:25000cells];',(50,))])
    def test_expanded_original_cli(self,tmp_path,body,strokes,entry,record_property):
        fixture=TransferMatrixFixture()
        load=f'{CELLS}:100000cells, {MEDIUM}:200uL' if 'cells' in body else f'{BUFFER}:200uL'
        plan=fixture.compile(fixture.source(body,load),tmp_path)
        context=fixture.context(tmp_path,plan)
        artifacts=tmp_path/'cli-artifacts'
        command=[str(Path(sys.executable).parent/'culsma')] if entry=='language' else [sys.executable,'-m','culsma_os.cli']
        result=subprocess.run([*command,'run',str(tmp_path/'protocol.culs'),'--driver','opentrons-simulator','--driver-config',str(context.config_path),'--artifacts-dir',str(artifacts),*(['--json'] if entry=='language' else [])],capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        if entry=='language':
            assert json.loads(result.stdout)['report']['os']['status']=='completed'
        artifact=json.loads((artifacts/'run.json').read_text())
        assert artifact['user_result']['os']['status']=='completed'
        receipts=[e['payload']['driver_payload'] for e in artifact['events'] if e['payload'].get('driver_code')=='OS_MATERIAL_REGISTERED']
        assert [t['volume_uL'] for r in receipts for t in r['transfers']]==pytest.approx(strokes)
        record_property('coverage',json.dumps({'status':'completed_'+entry+'_cli','strokes_uL':strokes}))
    @pytest.mark.parametrize('body', [
        'repeat 2 { target << [source:50uL]; }',
        'repeat 2 { repeat 2 { target << [source:25uL]; } }',
        'protocol Move(src,dst,amount) { dst << [src:amount]; } Move(src=source,dst=target,amount=50uL); Move(src=source,dst=target,amount=50uL);',
    ])
    def test_fixed_repeats_and_protocol_calls(self, tmp_path, body, record_property):
        fixture = TransferMatrixFixture()
        plan = fixture.compile(fixture.source(body), tmp_path)
        app = OSApplicationFactory().build(fixture.context(tmp_path, plan))
        try:
            result = app.execute(plan, init_state(plan))
            strokes = (25,25,25,25) if 'repeat 2 { repeat' in body else (50,50)
            evidence = fixture.assert_completed(app, plan, result, (100,100), strokes)
            record_property('coverage', json.dumps(evidence))
        finally:
            app.close()

    def test_imported_protocol(self, tmp_path, record_property):
        (tmp_path/'move.culs').write_text('protocol Move(src,dst,amount) { dst << [src:amount]; }')
        fixture=TransferMatrixFixture()
        plan=fixture.compile('include "move.culs";\n'+fixture.source('Move(src=source,dst=target,amount=50uL); Move(src=source,dst=target,amount=50uL);'),tmp_path)
        app=OSApplicationFactory().build(fixture.context(tmp_path,plan))
        try:
            result=app.execute(plan,init_state(plan))
            record_property('coverage',json.dumps(fixture.assert_completed(app,plan,result,(100,100),(50,50))))
        finally:
            app.close()

    @pytest.mark.parametrize('source_count,target_count',[(1,2),(3,1),(3,3)])
    @pytest.mark.parametrize('seed',[0,17,42])
    def test_generated_liquid_recipes(self,tmp_path,source_count,target_count,seed,record_property):
        import random
        rng=random.Random(seed)
        declarations=[]
        for i in range(source_count):
            declarations.append(f'let s{i} = tube(capacity=2000uL,load=[content(kind=formulation,type=buffer,code="S{i}"):1000uL]);')
        declarations.extend(f'let d{i} = tube(capacity=2000uL);' for i in range(target_count))
        draws=[[rng.choice([20,25,50,100,200]) for _ in range(source_count)] for _ in range(target_count)]
        body=[f'd{i} << ['+', '.join(f's{j}:{volume}uL' for j,volume in enumerate(row))+'];' for i,row in enumerate(draws)]
        fixture=TransferMatrixFixture()
        plan=fixture.compile('\n'.join(declarations+body),tmp_path)
        expected=tuple(1000-sum(row[j] for row in draws) for j in range(source_count))+tuple(sum(row) for row in draws)
        app=OSApplicationFactory().build(fixture.context(tmp_path,plan))
        try:
            result=app.execute(plan,init_state(plan))
            evidence=fixture.assert_completed(app,plan,result,expected,tuple(v for row in draws for v in row))
            # Independently authored component oracle, not only agreement with standalone runtime.
            containers=list(result.state.artifacts['material_state']['containers'].values())
            for i,row in enumerate(draws):
                assert containers[source_count+i]['components']=={f'S{j}':volume for j,volume in enumerate(row)}
            record_property('coverage',json.dumps(evidence))
        finally:
            app.close()

    @pytest.mark.parametrize('problem',['missing-binding','insufficient-tips'])
    def test_binding_and_consumable_rejections(self,tmp_path,problem,record_property):
        fixture=TransferMatrixFixture()
        plan=fixture.compile(fixture.source('target << [source:50uL,source:50uL];'),tmp_path)
        context=fixture.context(tmp_path,plan)
        if problem=='missing-binding':
            config=json.loads(context.config_path.read_text())
            del config['bindings'][next(reversed(config['bindings']))]
            context.config_path.write_text(json.dumps(config))
        app=OSApplicationFactory().build(context)
        backend=app.host.gateway.port.session.backend
        try:
            app.client.start()
            if problem=='insufficient-tips':
                backend.restore_consumables({'tips':95})
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['status']=='failed'
            code='WORKSPACE_BINDING_MISSING' if problem=='missing-binding' else 'DRV_OT_TIPS_INSUFFICIENT'
            assert code in ' '.join(d.message for d in result.diagnostics)
            assert not backend.protocol.commands()
            if problem=='missing-binding':
                assert result.user_result['os']['preflight']['status']=='rejected'
                assert not result.state.artifacts.get('material_state',{}).get('containers')
            else:
                assert fixture.volumes(result)==(200,0)
                assert result.user_result['os']['preflight']['status']=='passed'
            record_property('coverage',json.dumps({'status':'expected_rejection','diagnostic':code}))
        finally:
            app.close()

    def test_later_preparation_failure_keeps_previous_commit(self,tmp_path,record_property,monkeypatch):
        fixture=TransferMatrixFixture()
        plan=fixture.compile(fixture.source('target << [source:50uL]; target << [source:50uL];'),tmp_path)
        app=OSApplicationFactory().build(fixture.context(tmp_path,plan))
        original=app.host.gateway.prepare
        calls=[]
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise ValueError('DRIVER_LIVE_PREPARATION_REJECTED')
            return original(*args,**kwargs)
        monkeypatch.setattr(app.host.gateway,'prepare',fail_second)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert fixture.volumes(result)==(150,50)
            assert result.user_result['os']['preflight']['status']=='passed'
            assert 'DRIVER_LIVE_PREPARATION_REJECTED' in str(result.diagnostics)
            assert len(app.host.gateway.port.session.backend.receipts)==1
            assert not app.client.lifecycle.operations.resource.occupied()
            record_property('coverage',json.dumps({'status':'expected_rejection_after_confirmed_step','volumes_uL':[150,50]}))
        finally:
            app.close()

    @pytest.mark.parametrize('name,body',[
        ('separation-prerequisite','sep(sample=source,program=centrifuge_program(drive=12000g)); target << [source.contents[0]:50uL];'),
        ('runtime-declarations-in-repeat','repeat 2 { let another = tube(capacity=2000uL); another << [source:50uL]; }'),
    ])
    def test_unimplemented_host_profiles_reject_before_action(self,tmp_path,name,body,record_property):
        fixture=TransferMatrixFixture()
        plan=fixture.compile(fixture.source(body),tmp_path)
        app=OSApplicationFactory().build(fixture.context(tmp_path,plan))
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert 'HOST_OPERATION_UNSUPPORTED' in [d.code for d in result.diagnostics]
            assert not app.host.gateway.port.session.backend.protocol.commands()
            record_property('coverage',json.dumps({'status':'expected_host_profile_rejection','diagnostic':'HOST_OPERATION_UNSUPPORTED'}))
        finally:
            app.close()

