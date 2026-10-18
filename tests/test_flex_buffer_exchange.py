"""The same wash protocol on a passive block, with journaled field-removal moves."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from .test_magnetic_block import BlockFixture
from .test_flex_workstation import WorkstationDeviceFault

EXAMPLE=Path(__file__).resolve().parents[1]/'examples/magnetic-buffer-exchange'


class FlexBufferExchangeFixture:
    def build(self, directory, change=None):
        def configure(raw, plan):
            raw['labware_moves']={s.step_id:[{'labware':'assay','destination':'module:magnet'}]
                for protocol in plan.plans for s in protocol.steps if s.op=='sep'}
            if change is not None: change(raw, plan)
        return BlockFixture().build(directory, (EXAMPLE/'protocol.culs').read_text(), configure)

    def complete(self, app, plan, result):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan, StubDriver(), init_state(plan)); assert baseline.ok
        assert result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs']==baseline.state.artifacts['protocol_outputs']
        identity=result.user_result['os']['run_id']; session=app.host.gateway.port.session
        assert [c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values()]==[10,0,240,240]
        assert app.host.material.get(identity)[2]==9
        assert len(app.client.lifecycle.evidence.attempts_for_run(identity))==18
        assert session.motion.positions()['assay']=='D1' and session.motion.state['revision']==6
        assert not session.magnetic.held and session.backend.available_tips()==90
        assert app.client.lifecycle.reservations.get(identity).status=='released'
        assert not app.client.lifecycle.operations.resource.occupied()
        assert not app.client.lifecycle.operations.motions.motion.repository.pending('opentrons')
        return identity


class TestFlexBufferExchange:
    def test_same_program_and_materials(self, tmp_path):
        plan,context,app=FlexBufferExchangeFixture().build(tmp_path)
        try:
            assert (tmp_path/'protocol.culs').read_bytes()==(EXAMPLE/'protocol.culs').read_bytes()
            assert json.loads(context.config_path.read_text())==json.loads((EXAMPLE/'deck-flex.json').read_text())
            result=app.execute(plan,init_state(plan)); identity=FlexBufferExchangeFixture().complete(app,plan,result)
            session=app.host.gateway.port.session
            assert [r.payload['operation_kind'] for r in session.magnetic.receipts]==['magnetic_separation','magnetic_release']*3
            assert all(r.payload['phases']=={'verify_removed':'returned'} for r in session.magnetic.receipts[1::2])
            assert len(session.motion.receipts)==6 and len(session.backend.receipts)==6
            assert not any('Engaging' in c or 'Disengaging' in c for c in session.backend.protocol.commands())
            evidence=app.client.lifecycle.evidence
            moves=[a for a in evidence.attempts_for_run(identity) if a.context['description'].get('operation_kind')=='labware_move']
            assert len(moves)==6
            for a in moves:
                assert app.client.lifecycle.operations.motions.registered(a,evidence.find_evidence(a.effect_id))
                assert not app.host.material.registered(a.effect_id)
            assert all(app.client.lifecycle.conditions.release_completed(a) for a in app.client.lifecycle.conditions.activations(identity))
            for receipt in session.backend.receipts[1::2]:
                assert receipt.to_payload()['constraint_resolution'][0]['method_id']=='fresh-tip-per-stroke'
        finally: app.close()

    def test_preflight_projects_releases_without_mutation(self, tmp_path, monkeypatch):
        plan,_,app=FlexBufferExchangeFixture().build(tmp_path)
        try:
            lifecycle=app.client.lifecycle; session=app.host.gateway.port.session
            motion=lifecycle.operations.motions.motion
            before=deepcopy(motion.positions()); vendor=deepcopy(session.motion.state)
            original=motion.project_move; projections=[]
            def project(*args):
                value=original(*args); projections.append(value); return value
            def forbidden(*args,**kwargs): raise AssertionError('preflight crossed a write/device boundary')
            monkeypatch.setattr(motion,'project_move',project)
            for name in ('prepare_processing','prepare_labware_move','execute'):
                monkeypatch.setattr(app.host.gateway.port,name,forbidden)
            monkeypatch.setattr(lifecycle.operations.space.repository,'put',forbidden)
            state=init_state(plan); saved=deepcopy(state)
            report,diagnostics=app.client.execution.host.preflight.inspect(plan,state,'preview')
            assert not diagnostics and report['status']=='passed' and report['checked_effects']==9
            assert [r[0] for r in projections]==[2,4,6]
            assert all(r[1]['assay']=='D1' for r in projections)
            assert motion.positions()==before and session.motion.state==vendor and state==saved
            assert not session.backend.protocol.commands() and not session.magnetic.held
            assert not session.motion.receipts and not session.magnetic.receipts
            assert not lifecycle.evidence.attempts_for_run('preview')
        finally: app.close()

    def test_wash_occurs_off_block_with_parent_reservation(self, tmp_path, monkeypatch):
        plan,_,app=FlexBufferExchangeFixture().build(tmp_path); session=app.host.gateway.port.session
        original=session.backend.pipette.aspirate; observations=[]
        def observe(*args,**kwargs):
            identity=next(iter(app.client.lifecycle.runs.session_runs))
            assert app.client.lifecycle.reservations.get(identity).status=='active'
            observations.append((session.motion.positions()['assay'],bool(session.magnetic.held)))
            return original(*args,**kwargs)
        monkeypatch.setattr(session.backend.pipette,'aspirate',observe)
        try:
            result=app.execute(plan,init_state(plan)); FlexBufferExchangeFixture().complete(app,plan,result)
            assert observations==[('D1',False),('module:magnet',True)]*3
        finally: app.close()

    @pytest.mark.parametrize('hit',[1,2,3,4,5,6])
    @pytest.mark.parametrize('after',[False,True])
    def test_unknown_motion_stops_and_survives_restart(self, tmp_path, monkeypatch, hit, after):
        plan,context,app=FlexBufferExchangeFixture().build(tmp_path)
        session=app.host.gateway.port.session
        fault=WorkstationDeviceFault(session.backend.protocol.move_labware,hit,after)
        monkeypatch.setattr(session.backend.protocol,'move_labware',fault)
        try:
            result=app.execute(plan,init_state(plan)); identity=result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status']=='needs_reconciliation'
            assert fault.calls==hit and len(session.backend.receipts)==[1,2,3,4,5,6][hit-1]
            assert app.host.material.get(identity)[2]==[1,3,4,6,7,9][hit-1]
            assert session.motion.state['uncertain']
            assert app.client.lifecycle.operations.motions.motion.repository.pending('opentrons')
            assert app.client.lifecycle.reservations.get(identity).status=='active'
        finally: app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity); restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='needs_reconciliation'
            assert restarted.client.lifecycle.reservations.get(identity).status=='active'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally: restarted.close()

    @pytest.mark.parametrize('hit',[1,3])
    def test_saved_release_recovers_without_moving_again(self, tmp_path, monkeypatch, hit):
        plan,context,app=FlexBufferExchangeFixture().build(tmp_path)
        resource=app.client.lifecycle.operations.resource; original=resource.settle; seen=[]
        def crash(attempt_id,evidence):
            if evidence.payload.get('operation_kind')=='magnetic_release' and evidence.effect_id not in seen:
                seen.append(evidence.effect_id)
                if len(seen)==hit: raise KeyboardInterrupt('after durable release receipt')
            return original(attempt_id,evidence)
        monkeypatch.setattr(resource,'settle',crash)
        try:
            with pytest.raises(KeyboardInterrupt): app.execute(plan,init_state(plan))
            identity=next(iter(app.client.lifecycle.runs.session_runs))
            assert app.host.gateway.port.session.motion.state['revision']==hit*2
        finally: app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity); restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='completed'
            FlexBufferExchangeFixture().complete(restarted,plan,restarted.host.result(identity))
            assert len(restarted.host.gateway.port.session.motion.receipts)==6-hit*2
        finally: restarted.close()

    @pytest.mark.parametrize('problem',['missing-second','wrong-second','duplicate-dock'])
    def test_invalid_route_rejects_before_actions(self, tmp_path, problem):
        def change(raw,plan):
            keys=list(raw['labware_moves'])
            if problem=='missing-second': raw['labware_moves'].pop(keys[1])
            elif problem=='wrong-second': raw['labware_moves'][keys[1]][0]['destination']='D2'
            else: raw['labware_moves'][keys[0]]*=2
        plan,_,app=FlexBufferExchangeFixture().build(tmp_path,change)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['preflight']['status']=='rejected'
            assert 'registered_material' not in result.user_result['os']
            assert not app.client.lifecycle.evidence.attempts_for_run(result.user_result['os']['run_id'])
            assert not app.client.lifecycle.operations.resource.occupied()
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally: app.close()

    @pytest.mark.parametrize('entry',['os','language'])
    def test_cli_entries(self,tmp_path,entry):
        _,context,app=FlexBufferExchangeFixture().build(tmp_path); app.close()
        artifacts=tmp_path/'cli'
        completed=subprocess.run([sys.executable,'-m','culsma_os.cli' if entry=='os' else 'culsma.cli','run',
            str(EXAMPLE/'protocol.culs'),'--driver','opentrons-simulator','--driver-config',str(context.config_path),
            '--artifacts-dir',str(artifacts)],capture_output=True,text=True)
        assert completed.returncode==0,completed.stdout+completed.stderr
        result=json.loads((artifacts/'run.json').read_text())
        assert result['ok'] and result['user_result']['os']['status']=='completed'

    def test_saved_removal_registers_without_guessing_live_release(self, tmp_path, monkeypatch):
        plan,context,app=FlexBufferExchangeFixture().build(tmp_path)
        motion=app.client.lifecycle.operations.motions.motion; original=motion.register
        def crash(attempt,fact):
            if attempt.context['description']['motion_intent']['destination']=='D1':
                raise KeyboardInterrupt('after removal receipt before station registration')
            return original(attempt,fact)
        monkeypatch.setattr(motion,'register',crash)
        try:
            with pytest.raises(KeyboardInterrupt): app.execute(plan,init_state(plan))
            identity=next(iter(app.client.lifecycle.runs.session_runs))
            assert motion.repository.pending('opentrons')
        finally: app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity); restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='needs_reconciliation'
            registered=restarted.client.lifecycle.operations.motions.motion
            assert registered.positions()[0]==2 and registered.positions()[1]['assay']=='D1'
            assert not registered.repository.pending('opentrons')
            assert restarted.client.lifecycle.reservations.get(identity).status=='active'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.conditions.outstanding(identity)
        finally: restarted.close()

    @pytest.mark.parametrize('problem',['occupied','wrong-source','unsupported-destination'])
    def test_projected_release_rejects_invalid_positions(self,tmp_path,problem):
        _,_,app=FlexBufferExchangeFixture().build(tmp_path)
        try:
            motion=app.client.lifecycle.operations.motions.motion
            positions=deepcopy(motion.positions()[1]);positions['assay']='module:magnet'
            source='module:magnet';destination='D1'
            if problem=='occupied':positions['other']='D1'
            elif problem=='wrong-source':source='D2'
            else:destination='invalid'
            projected=(1,positions);saved=deepcopy(projected)
            with pytest.raises(ValueError):motion.project_move('assay',source,destination,projected)
            assert projected==saved and motion.positions()[0]==0
        finally:app.close()

    def test_projection_boundary(self):
        root=EXAMPLE.parents[1]/'src/culsma_os'
        preflight=(root/'program_manager/interactors/preflight.py').read_text()
        assert 'ConditionPreflightPort' in preflight
        assert 'processing_engine' not in preflight and 'magnetic' not in preflight
        source=(root/'processing_engine/interactors/conditions.py').read_text().split('class ProcessingConditionProjectionInteractor:',1)[1]
        for forbidden in ('gateway','record_intent','repository','execute(','.held'):
            assert forbidden not in source
