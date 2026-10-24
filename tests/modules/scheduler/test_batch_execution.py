"""Whole-run coordination against a labelled batch backend; no vendor IO."""
from dataclasses import replace
from types import SimpleNamespace
import pytest

from culsma_os.device_manager.models import ExecutionFeedbackCapabilities
from tests.support.common import FakeSessionFactory, FakeDevicePort, ProgramFixture


class BatchDevicePort(FakeDevicePort):
    execution_mode = 'batch'

    def __init__(self):
        super().__init__()
        self.outcome = 'completed'
        self.before_return = None

    def prepare_batch(self, step_id, operations):
        return SimpleNamespace(step_id=step_id, operations=operations)

    def describe_batch(self, plan):
        return {'member_step_ids': [o.intent.step_id for o in plan.operations],
                'resource_requirements': {'tips': sum(len(o.intent.aliquots) for o in plan.operations)}}

    def execute(self, plan, attempt_id):
        self.executions.append((plan, attempt_id))
        count = self.describe_batch(plan)['resource_requirements']['tips'] if self.outcome == 'completed' else 0
        self.remaining -= count
        if self.before_return is not None:
            self.before_return()
        return {'outcome': self.outcome, 'mode': 'simulation', 'step_id': plan.step_id,
                'configuration_revision': 'r1', 'consumed_resources': {'tips': count} if count else {},
                'payload': {'source': 'batch-test-double', 'feedback_scope': 'batch'}}


class BatchSessionFactory(FakeSessionFactory):
    def build(self, context):
        _, snapshot, positions, capacities, mapper = super().build(context)
        port = BatchDevicePort()
        self.ports[-1] = port
        snapshot = replace(snapshot, feedback_capabilities=ExecutionFeedbackCapabilities(('operation', 'batch')))
        return port, snapshot, positions, capacities, mapper


class TestBatchExecution:
    def begin(self, tmp_path):
        factory = BatchSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        return factory, app, app.client.submit_run(ProgramFixture.request())

    def test_batch_projection_does_not_confirm_or_write_state(self, tmp_path):
        factory, app, run_id = self.begin(tmp_path)
        try:
            lifecycle = app.client.lifecycle
            lifecycle.runs.advance_ready(run_id)
            before = app.client.get_run(run_id)
            units, operations = app.client.execution.project_batch(run_id)
            assert len(units) == len(operations) == 2
            assert app.client.get_run(run_id) == before
            assert lifecycle.operations.evidence.attempts_for_run(run_id) == ()
            assert factory.ports[0].remaining == 96 and factory.ports[0].executions == []
            with pytest.raises(KeyError): lifecycle.operations.material.get(run_id)
            assert app.client.execution.host.restore(before.checkpoint)[0]['confirmed'] == []
        finally:
            app.close()

    def test_batch_program_submits_one_method(self, tmp_path):
        factory, app, run_id = self.begin(tmp_path)
        try:
            assert app.client.run_until_settled(run_id).status == 'completed'
            ops = app.client.lifecycle.operations
            assert len(factory.ports[0].executions) == 1 and factory.ports[0].remaining == 94
            attempts = ops.evidence.attempts_for_run(run_id)
            assert len(attempts) == 3
            root = next(a for a in attempts if 'execution_batch' in a.context['description'])
            assert ops.evidence.find_evidence(root.effect_id).consumed_resources == {'tips': 2}
            for member in root.context['member_effect_ids']:
                evidence = ops.evidence.find_evidence(member)
                assert evidence.payload['completion_coverage'] == 'derived_from_batch'
                assert evidence.payload['shared_evidence_id'] == root.attempt_id + ':receipt'
                assert evidence.consumed_resources == {}
            assert ops.material.get(run_id)[2] == 2
            assert not ops.resource.occupied()
            assert app.client.lifecycle.reservations.get(run_id).status == 'released'
        finally:
            app.close()

    def test_second_batch_uses_next_tips_and_same_station_ownership(self, tmp_path):
        factory, app, first = self.begin(tmp_path)
        try:
            second = app.client.submit_run(ProgramFixture.request())
            assert app.client.run_until_settled(first).status == 'completed'
            assert app.client.run_until_settled(second).status == 'completed'
            assert len(factory.ports[0].executions) == 2 and factory.ports[0].remaining == 92
            assert app.client.lifecycle.operations.evidence.known_consumption('fake') == {'tips': 4}
        finally:
            app.close()

    def test_unknown_batch_has_no_registration_and_no_replay(self, tmp_path):
        factory, app, run_id = self.begin(tmp_path)
        try:
            factory.ports[0].outcome = 'unknown'
            assert app.client.run_until_settled(run_id).status == 'needs_reconciliation'
            assert app.client.lifecycle.operations.material.get(run_id)[2] == 0
            assert len(app.client.lifecycle.operations.evidence.attempts_for_run(run_id)) == 1
            assert app.client.lifecycle.operations.resource.occupied()
            app.client.run_until_settled(run_id)
            other = app.client.submit_run(ProgramFixture.request())
            assert app.client.run_until_settled(other).status == 'ready'
            assert len(factory.ports[0].executions) == 1
        finally:
            app.close()

    @pytest.mark.parametrize('point', ['before-evidence', 'first-registration', 'second-registration', 'after-checkpoint'])
    def test_saved_batch_evidence_repairs_without_device_calls(self, tmp_path, monkeypatch, point):
        factory, app, run_id = self.begin(tmp_path)
        ops = app.client.lifecycle.operations
        original = ops.material.reconcile
        calls = []
        def crash(*args):
            raise KeyboardInterrupt('batch crash window')
        def register(*args):
            calls.append(args)
            if len(calls) == (2 if point == 'second-registration' else 1): crash()
            return original(*args)
        target, method, replacement = ((ops.evidence, 'ingest', crash) if point == 'before-evidence'
            else (ops.resource, 'settle', crash) if point == 'after-checkpoint'
            else (ops.material, 'reconcile', register))
        monkeypatch.setattr(target, method, replacement)
        with pytest.raises(KeyboardInterrupt): app.client.run_until_settled(run_id)
        app.close()
        restarted = factory.open(tmp_path)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            status = restarted.client.run_until_settled(run_id).status
            assert status == ('needs_reconciliation' if point == 'before-evidence' else 'completed')
            assert factory.ports[-1].executions == []
            if point != 'before-evidence':
                assert restarted.client.lifecycle.operations.material.get(run_id)[2] == 2
                assert not restarted.client.lifecycle.operations.resource.occupied()
            else:
                assert restarted.client.lifecycle.operations.resource.occupied()
        finally:
            restarted.close()

    @pytest.mark.parametrize('action', ['pause', 'cancel'])
    def test_pause_or_cancel_during_batch_never_resubmits(self, tmp_path, action):
        factory, app, run_id = self.begin(tmp_path)
        try:
            factory.ports[0].before_return = lambda: app.client.tasks.pause_dispatch(run_id) if action == 'pause' else app.client.tasks.request_cancel(run_id)
            result = app.client.run_until_settled(run_id)
            assert result.status == ('paused' if action == 'pause' else 'cancelled')
            if action == 'pause':
                app.client.resume_run(run_id)
                assert app.client.run_until_settled(run_id).status == 'completed'
            assert len(factory.ports[0].executions) == 1
        finally:
            app.close()

    def test_invalid_batch_has_no_vendor_calls(self, tmp_path, monkeypatch):
        factory, app, run_id = self.begin(tmp_path)
        try:
            monkeypatch.setattr(factory.ports[0], 'describe_batch', lambda plan:
                {'member_step_ids': [], 'resource_requirements': {'tips': 2}})
            assert app.client.run_until_settled(run_id).status == 'failed'
            assert factory.ports[0].executions == []
            assert app.client.lifecycle.operations.evidence.attempts_for_run(run_id) == ()
            assert not app.client.lifecycle.operations.resource.occupied()
        finally:
            app.close()


    @pytest.mark.parametrize('all_logical', [False, True])
    def test_zero_volume_steps_remain_logical_completions(self, tmp_path, all_logical):
        from culsma_os.program_manager.interactors.compilation import CompilationInteractor
        from culsma_os.program_manager.models import RunRequest
        source = tmp_path/'logical.culs'
        code = ProgramFixture.source.read_text().replace('alias:50uL', 'alias:0uL')
        if all_logical:
            code = code.replace('source:0.05mL', 'source:0uL')
        source.write_text(code)
        compiled = CompilationInteractor().compile([source])
        factory = BatchSessionFactory()
        app = factory.open(tmp_path)
        try:
            app.client.start()
            run_id = app.client.submit_run(RunRequest(compiled.plan, compiled.state))
            assert app.client.run_until_settled(run_id).status == 'completed'
            assert len(factory.ports[0].executions) == (0 if all_logical else 1)
            assert factory.ports[0].remaining == (96 if all_logical else 95)
            assert app.client.lifecycle.operations.evidence.known_consumption('fake') == ({} if all_logical else {'tips': 1})
        finally:
            app.close()

    def test_changed_recipe_and_snapshot_are_rejected_without_registration(self, tmp_path):
        factory, app, run_id = self.begin(tmp_path)
        try:
            app.client.lifecycle.runs.advance_ready(run_id)
            units, _ = app.client.execution.project_batch(run_id)
            manifest = app.client.execution.describe_batch(units)
            with pytest.raises(ValueError, match='BATCH_REPLAY_MISMATCH'):
                app.client.execution.restore_batch({**manifest, 'units_fingerprint': 'foreign'})
            with pytest.raises(ValueError, match='BATCH_SNAPSHOT_STALE'):
                app.client.execution.verify_batch_snapshot(run_id, {**manifest, 'initial_checkpoint': 'foreign'}, units)
            assert not factory.ports[0].executions
            with pytest.raises(KeyError): app.client.lifecycle.operations.material.get(run_id)
        finally:
            app.close()
