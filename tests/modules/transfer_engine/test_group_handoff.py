from dataclasses import replace
import pytest
from culsma.runtime.state import init_state
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest, PendingEffectGroup
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from tests.support.transfer_engine.plate96 import PlateFixture, BUFFER
from tests.support.program_manager.hosted_semantics import HostedRuntimeFixture as HostedTestFixture
from tests.support.transfer_engine.group_handoff import SOURCE, GroupFixture


def test_official_simulator_group_handoff(tmp_path):
    plan,context,app=GroupFixture().build(tmp_path)
    try:
        run_id,pending=GroupFixture().pending(app,plan)
        calls=[];original=app.client.lifecycle.operations.groups.dispatch
        def counted(*args):
            calls.append(args[1].effect_id);return original(*args)
        app.client.lifecycle.operations.groups.dispatch=counted
        record=app.client.run_until_settled(run_id)
        result=app.client.result(run_id)
        assert record.status=='completed' and result.ok and calls==[pending.effect_id]
        assert result.state.artifacts['material_state']==run(plan,StubDriver()).state.artifacts['material_state']
        assert len(app.host.gateway.port.session.backend.receipts)==8
        assert not app.client.lifecycle.operations.resource.occupied()
        host=app.client.execution.host
        data=host.codec.loads(record.checkpoint)
        assert data['schema']==3 and len(data['confirmed'])==1
        assert len(data['confirmed'][0].resolution.members)==8
        group_evidence=app.client.lifecycle.evidence.find_evidence(pending.effect_id)
        assert group_evidence.outcome=='completed' and group_evidence.consumed_resources=={}
        assert sum(app.client.lifecycle.evidence.known_consumption(app.client.lifecycle.device_id).values())==8
    finally:app.close()


def test_group_unknown_preserves_prefix_and_does_not_reexecute(tmp_path,monkeypatch):
    plan,context,app=GroupFixture().build(tmp_path)
    run_id=None
    try:
        backend=app.host.gateway.port.session.backend
        original=backend.pipette.dispense;calls=[]
        def failing(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('group second dispense failure')
            return original(*args,**kwargs)
        monkeypatch.setattr(backend.pipette,'dispense',failing)
        result=app.execute(plan,init_state(plan));run_id=result.user_result['os']['run_id']
        assert not result.ok and len(calls)==2
        assert app.client.lifecycle.operations.resource.occupied()
        registered=result.user_result['os']['registered_material']['state']['containers'].values()
        volumes={c['metadata'].get('label'):c['volume_uL'] for c in registered}
        assert volumes['Stock']==980 and volumes['Assay_A1']==20 and volumes['Assay_B1']==0
    finally:app.close()
    restarted=OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(run_id)
        restarted.client.start()
        assert restarted.client.get_run(run_id).status=='needs_reconciliation'
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
        assert restarted.client.lifecycle.operations.resource.occupied()
        assert restarted.client.run_until_settled(run_id).status=='needs_reconciliation'
        assert not restarted.host.gateway.port.session.backend.receipts
    finally:restarted.close()


def test_group_recovery_registers_saved_evidence(tmp_path,monkeypatch):
    plan,context,app=GroupFixture().build(tmp_path)
    run_id,pending=GroupFixture().pending(app,plan)
    def crash(*args):raise KeyboardInterrupt('after group facts before semantic resume')
    monkeypatch.setattr(app.client.lifecycle.operations.state,'mark_ready',crash)
    with pytest.raises(KeyboardInterrupt):app.client.lifecycle.operations.dispatch_ready(run_id)
    assert len(app.host.gateway.port.session.backend.receipts)==8
    app.close()
    restarted=OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(run_id)
        restarted.client.start()
        assert restarted.client.run_until_settled(run_id).status=='completed'
        assert restarted.client.result(run_id).ok
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
        assert not restarted.host.gateway.port.session.backend.receipts
        assert restarted.host.gateway.port.session.backend.available_tips()==88
        assert not restarted.client.lifecycle.operations.resource.occupied()
    finally:restarted.close()


def test_legacy_group_checkpoint_stays_scalar(tmp_path):
    fixture=PlateFixture();plan=fixture.compile(SOURCE,tmp_path)
    host=HostedRuntimeInteractor();data=host.codec.loads(host.create(plan,init_state(plan),'legacy'))
    data['schema']=2;checkpoint=host.codec.dumps(data);seen=[];helper=HostedTestFixture()
    for _ in range(9):
        checkpoint=host.advance(checkpoint);pending=host.pending(checkpoint)
        if pending is None:break
        assert not isinstance(pending,PendingEffectGroup)
        seen.append(pending.effect_id);checkpoint=host.resume(checkpoint,helper.resolution(host,pending))
    assert len(seen)==8 and host.result(checkpoint).ok


def test_group_permit_is_held_across_members(tmp_path,monkeypatch):
    plan,context,app=GroupFixture().build(tmp_path)
    seen=[];original=app.host.gateway.execute_group_member
    def checking(*args):
        permit=args[2]
        assert app.client.lifecycle.operations.resource.occupied()==tuple(sorted(permit.resources))
        app.client.lifecycle.operations.resource.validate_active_permit(permit)
        seen.append(permit.attempt_id)
        return original(*args)
    monkeypatch.setattr(app.host.gateway,'execute_group_member',checking)
    try:
        result=app.execute(plan,init_state(plan))
        assert result.ok and len(seen)==8 and len(set(seen))==1
    finally:app.close()


def test_group_binds_one_layout_snapshot(tmp_path,monkeypatch):
    plan,context,app=GroupFixture().build(tmp_path)
    space=app.client.lifecycle.operations.space;original=space.bind;calls=[]
    def counting(*args):
        calls.append(args[0]);return original(*args)
    monkeypatch.setattr(space,'bind',counting)
    try:
        result=app.execute(plan,init_state(plan))
        assert result.ok and len(calls)==1
        assert len(app.host.gateway.port.session.backend.receipts)==8
    finally:app.close()


def test_group_hardware_admission_rejects_before_any_action(tmp_path):
    source=SOURCE.replace('assay[A1:H1] << [stock:20uL];','assay[A1:A2] << [series(stock,[10uL,25uL])];')
    plan,context,app=PlateFixture().run_case(tmp_path,source,'p20_single_gen2')
    try:
        result=app.execute(plan,init_state(plan))
        assert not result.ok
        assert any('DRV_OT_VOLUME_RANGE' in d.message for d in result.diagnostics)
        assert not app.host.gateway.port.session.backend.protocol.commands()
        assert not app.client.lifecycle.operations.resource.occupied()
    finally:app.close()


def test_mixed_scalar_group_scalar_preserves_order_and_state(tmp_path):
    source=SOURCE.replace('assay[A1:H1] << [stock:20uL];','let wells=assay[A1:H1]; wells[0] << [stock:10uL]; wells << [stock:20uL]; stock << [wells[7]:5uL];')
    plan,context,app=PlateFixture().run_case(tmp_path,source,'p20_single_gen2')
    try:
        result=app.execute(plan,init_state(plan))
        assert result.ok
        assert result.state.artifacts['material_state']==run(plan,StubDriver()).state.artifacts['material_state']
        data=app.client.execution.host.codec.loads(app.client.get_run(result.user_result['os']['run_id']).checkpoint)
        assert [type(r).__name__ for r in data['confirmed']]==['RecordedEffect','RecordedEffectGroup','RecordedEffect']
        assert len(app.host.gateway.port.session.backend.receipts)==10
        assert not app.client.lifecycle.operations.resource.occupied()
    finally:app.close()


def test_crash_after_device_return_without_evidence_never_replays(tmp_path,monkeypatch):
    plan,context,app=GroupFixture().build(tmp_path)
    run_id,pending=GroupFixture().pending(app,plan)
    evidence=app.client.lifecycle.evidence;original=evidence.ingest;calls=[]
    def crash_before_save(value):
        calls.append(value)
        if len(calls)==2:raise KeyboardInterrupt('device returned before evidence persisted')
        return original(value)
    monkeypatch.setattr(evidence,'ingest',crash_before_save)
    with pytest.raises(KeyboardInterrupt):app.client.lifecycle.operations.dispatch_ready(run_id)
    assert len(app.host.gateway.port.session.backend.receipts)==2
    app.close()
    restarted=OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(run_id)
        restarted.client.start()
        assert restarted.client.get_run(run_id).status=='needs_reconciliation'
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
        assert restarted.client.lifecycle.evidence.find_evidence(pending.members[0].effect_id) is not None
        assert restarted.client.lifecycle.evidence.find_evidence(pending.members[1].effect_id) is None
        assert restarted.client.lifecycle.operations.resource.occupied()
    finally:restarted.close()

