import json
from dataclasses import replace
import pytest
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
from tests.support.processing_engine.processing_magnetic import MagneticFixture, SOURCE
from tests.support.workspace_manager.magnetic_block import BlockFixture


def test_passive_separation_and_registered_release(tmp_path):
    plan,context,app=BlockFixture().build(tmp_path)
    try:
        result=app.execute(plan,init_state(plan))
        identity=MagneticFixture().compare(app,plan,result)
        session=app.host.gateway.port.session
        assert session.backend.protocol.is_simulating()
        assert session.magnetic.receipts[0].payload['phases']=={'verify_docked':'returned','wait':'returned'}
        assert session.magnetic.receipts[1].payload['phases']=={'verify_removed':'returned'}
        assert session.motion.state['revision']==2 and session.motion.positions()['assay']=='D1'
        assert not any('Engag' in c or 'Disengag' in c for c in session.backend.protocol.commands())
        attempts=app.client.lifecycle.operations.evidence.attempts_for_run(identity)
        moves=[a for a in attempts if a.context['description'].get('operation_kind')=='labware_move']
        assert len(moves)==2
        assert any(a.effect_id.endswith('/condition-release/motion') for a in moves)
        assert all(app.client.lifecycle.operations.motions.registered(a,
            app.client.lifecycle.operations.evidence.find_evidence(a.effect_id)) for a in moves)
        assert not session.magnetic.held
    finally:app.close()


def test_block_requires_docking(tmp_path):
    def change(raw,plan):
        raw['labware_moves']={next(s.step_id for p in plan.plans for s in p.steps if s.op=='Mutation'):
            [{'labware':'assay','destination':'D2'}]}
    plan,context,app=BlockFixture().build(tmp_path,change=change)
    try:
        result=app.execute(plan,init_state(plan))
        assert not result.ok
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:app.close()


def test_block_unknown_dwell(tmp_path,monkeypatch):
    plan,context,app=BlockFixture().build(tmp_path)
    try:
        def fail(**kwargs):raise TimeoutError('unknown dwell')
        monkeypatch.setattr(app.host.gateway.port.session.backend.protocol,'delay',fail)
        result=app.execute(plan,init_state(plan))
        assert not result.ok
        identity=result.user_result['os']['run_id']
        assert app.client.lifecycle.reservations.get(identity).status=='active'
        assert app.host.gateway.port.session.motion.positions()['assay']=='module:magnet'
        assert len(app.host.gateway.port.session.motion.receipts)==1
    finally:app.close()


@pytest.mark.parametrize('after_return',[False,True])
def test_block_unknown_removal(tmp_path,monkeypatch,after_return):
    plan,context,app=BlockFixture().build(tmp_path)
    backend=app.host.gateway.port.session.backend
    original=backend.protocol.move_labware
    def move(labware,new_location,**kwargs):
        if new_location=='D1':
            if after_return:original(labware,new_location,**kwargs)
            raise TimeoutError('unknown removal')
        return original(labware,new_location,**kwargs)
    monkeypatch.setattr(backend.protocol,'move_labware',move)
    try:
        result=app.execute(plan,init_state(plan))
        assert not result.ok
        identity=result.user_result['os']['run_id']
        assert app.client.lifecycle.reservations.get(identity).status=='active'
        assert app.client.lifecycle.conditions.outstanding(identity)
        assert len(app.host.gateway.port.session.magnetic.receipts)==1
        assert app.host.gateway.port.session.motion.state['uncertain']
        assert app.client.lifecycle.operations.motions.motion.repository.pending('opentrons')
    finally:app.close()
    restarted=OSApplicationFactory().build(context)
    try:
        restarted.client.start()
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
        assert restarted.client.lifecycle.reservations.get(identity).status=='active'
        assert restarted.client.lifecycle.conditions.outstanding(identity)
    finally:restarted.close()


@pytest.mark.parametrize('point',['after-dwell','after-release'])
def test_block_crash_recovery_never_replays_device(tmp_path,monkeypatch,point):
    plan,context,app=BlockFixture().build(tmp_path)
    lifecycle=app.client.lifecycle
    if point=='after-dwell':
        identity,_=MagneticFixture().waiting_separation(app,plan)
        original=lifecycle.operations.material.reconcile
        def crash(pending,evidence):
            if evidence.payload.get('operation_kind')=='magnetic_separation':raise KeyboardInterrupt('after dwell')
            return original(pending,evidence)
        monkeypatch.setattr(lifecycle.operations.material,'reconcile',crash)
        action=lambda:lifecycle.operations.dispatch_ready(identity)
    else:
        original=lifecycle.operations.resource.settle
        def crash(attempt_id,evidence):
            if evidence.payload.get('operation_kind')=='magnetic_release':raise KeyboardInterrupt('after release')
            return original(attempt_id,evidence)
        monkeypatch.setattr(lifecycle.operations.resource,'settle',crash)
        action=lambda:app.execute(plan,init_state(plan))
    try:
        with pytest.raises(KeyboardInterrupt):action()
        identity=next(iter(lifecycle.runs.session_runs))
    finally:app.close()
    restarted=OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity);restarted.client.start()
        record=restarted.client.run_until_settled(identity)
        assert record.status==('completed' if point=='after-release' else 'failed') or (point=='after-dwell' and record.status=='needs_reconciliation')
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
        assert restarted.client.lifecycle.reservations.get(identity).status==('released' if point=='after-release' else 'active')
    finally:restarted.close()


def test_completed_block_release_is_idempotent(tmp_path):
    plan,context,app=BlockFixture().build(tmp_path)
    try:
        result=app.execute(plan,init_state(plan));assert result.ok
        identity=result.user_result['os']['run_id']
        session=app.host.gateway.port.session
        before=tuple(session.backend.protocol.commands())
        app.client.lifecycle.conditions.finish(identity)
        assert tuple(session.backend.protocol.commands())==before
        assert session.motion.state['revision']==2
    finally:app.close()


def test_block_release_requires_station_registration(tmp_path,monkeypatch):
    plan,context,app=BlockFixture().build(tmp_path)
    try:
        result=app.execute(plan,init_state(plan));assert result.ok
        identity=result.user_result['os']['run_id']
        conditions=app.client.lifecycle.conditions
        activation=conditions.activations(identity)[0]
        assert conditions.release_completed(activation)
        monkeypatch.setattr(conditions.motions,'registered',lambda attempt,fact:False)
        assert not conditions.release_completed(activation)
    finally:app.close()


def test_block_resident_fifo_runs(tmp_path):
    from culsma_os.lifecycle_manager.models import ResidentHostSettings
    from tests.support.integration.resident_host import ResidentHarness
    plan,context,app=BlockFixture().build(tmp_path)
    app.close()
    class BlockResidentHarness(ResidentHarness):
        def serve(self):
            try:
                self.host=OSApplicationFactory().build_resident_host(self.settings)
                self.host.serve()
            except BaseException as error:
                self.errors.append(error)
    harness=BlockResidentHarness(tmp_path)
    harness.context=context
    harness.settings=ResidentHostSettings(context,harness.endpoint,0.01)
    try:
        harness.start()
        requests=[harness.client.execute({'action':'submit','source':str(tmp_path/'protocol.culs')}) for _ in range(2)]
        identities=[request['run_id'] for request in requests]
        for identity in identities:harness.wait(lambda:harness.status(identity)['status']=='completed')
        inspection=harness.client.execute({'action':'device-status'})
        assert inspection
        import sqlite3
        from culsma_os.resource_manager.interactors import StationPathInteractor
        with sqlite3.connect(StationPathInteractor().database_path(context)) as connection:
            row=connection.execute('SELECT revision,positions FROM os_labware_positions').fetchone()
            assert row[0]==4 and json.loads(row[1])['assay']=='D1'
            assert connection.execute('SELECT COUNT(*) FROM os_motion_registrations').fetchone()[0]==4
    finally:harness.stop()

