"""Selection contract only: a batch probe does not generate or run vendor code."""
from dataclasses import FrozenInstanceError, replace

import pytest

from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.device_manager.models import ExecutionFeedbackCapabilities
from culsma_os.program_manager.models import HostBuildContext, RunRecord
from culsma_os.scheduler.interactors import ExecutionStrategyInteractor
from culsma_os.scheduler.models import ExecutionMode
from tests.support.common import FakeSessionFactory, ProgramFixture


class ExecutionFixture:
    def __init__(self, status="ready", advance_status="waiting", dispatch_status="ready"):
        self.record = RunRecord("run", status, "checkpoint")
        self.advance_status = advance_status
        self.dispatch_status = dispatch_status
        self.calls = []

    def get(self, run_id):
        assert run_id == self.record.run_id
        return self.record

    def advance_ready(self, run_id):
        self.calls.append(("advance", run_id))
        self.record = replace(self.record, status=self.advance_status, revision=self.record.revision + 1)
        return self.record

    def dispatch_ready(self, run_id):
        self.calls.append(("dispatch", run_id))
        self.record = replace(self.record, status=self.dispatch_status, revision=self.record.revision + 1)


class BatchProbe:
    """Observe routing; deliberately performs no device execution or registration."""

    def __init__(self, tasks):
        self.tasks = tasks
        self.calls = []

    def execute(self, run_id):
        self.calls.append(run_id)
        return self.tasks.get(run_id)


class StrategyProbeFactory:
    def __init__(self):
        self.probe = None

    def __call__(self, tasks, runs, operations):
        self.probe = BatchProbe(tasks)
        return ExecutionStrategyInteractor(tasks, runs, operations, ExecutionMode.BATCH, self.probe)


class TestExecutionStrategy:
    @pytest.mark.parametrize("mode", [ExecutionMode.STEPWISE, "stepwise"])
    @pytest.mark.parametrize("status,after_advance,after_dispatch,expected,calls", [
        ("ready", "waiting", "ready", "ready", ["advance", "dispatch"]),
        ("ready", "ready", "ready", "ready", ["advance"]),
        ("ready", "finalizing", "ready", "finalizing", ["advance"]),
        ("waiting", "waiting", "ready", "ready", ["dispatch"]),
        ("waiting", "waiting", "needs_reconciliation", "needs_reconciliation", ["dispatch"]),
    ])
    def test_stepwise_preserves_advancement_and_blocking(self, mode, status, after_advance, after_dispatch, expected, calls):
        fixture = ExecutionFixture(status, after_advance, after_dispatch)
        batch = BatchProbe(fixture)
        strategy = ExecutionStrategyInteractor(fixture, fixture, fixture, mode, batch)
        record = strategy.execute("run")
        assert record is fixture.record and record.status == expected
        assert fixture.calls == [(call, "run") for call in calls]
        assert batch.calls == []
        assert strategy.mode is ExecutionMode.STEPWISE

    @pytest.mark.parametrize("mode", [ExecutionMode.BATCH, "batch"])
    @pytest.mark.parametrize("status", ["ready", "waiting"])
    def test_batch_uses_only_the_injected_run_executor(self, mode, status):
        fixture = ExecutionFixture(status)
        batch = BatchProbe(fixture)
        strategy = ExecutionStrategyInteractor(fixture, fixture, fixture, mode, batch)
        assert strategy.execute("run") is fixture.record
        assert batch.calls == ["run"]
        assert fixture.calls == []

    @pytest.mark.parametrize("status", ["paused", "needs_reconciliation", "cancel_requested", "finalizing", "completed", "failed", "cancelled"])
    @pytest.mark.parametrize("mode", list(ExecutionMode))
    def test_non_runnable_runs_do_not_enter_either_executor(self, mode, status):
        fixture = ExecutionFixture(status)
        batch = BatchProbe(fixture)
        strategy = ExecutionStrategyInteractor(fixture, fixture, fixture, mode, batch)
        assert strategy.execute("run") is fixture.record
        assert batch.calls == fixture.calls == []

    @pytest.mark.parametrize("mode", ["", "automatic", "simulation", "final-only", True, 1, None])
    def test_unknown_mode_is_rejected_before_any_execution(self, mode):
        fixture = ExecutionFixture()
        with pytest.raises(ValueError, match="^EXECUTION_MODE_UNSUPPORTED$"):
            ExecutionStrategyInteractor(fixture, fixture, fixture, mode)
        assert fixture.calls == []

    @pytest.mark.parametrize("mode", [ExecutionMode.BATCH, "batch"])
    def test_missing_batch_executor_never_falls_back_to_stepwise(self, mode):
        fixture = ExecutionFixture()
        with pytest.raises(ValueError, match="^EXECUTION_BATCH_NOT_CONFIGURED$"):
            ExecutionStrategyInteractor(fixture, fixture, fixture, mode)
        assert fixture.calls == []

    def test_mode_and_executor_cannot_change_after_construction(self):
        fixture = ExecutionFixture()
        strategy = ExecutionStrategyInteractor(fixture, fixture, fixture)
        for field, value in [("mode", ExecutionMode.BATCH), ("batch", BatchProbe(fixture))]:
            with pytest.raises(FrozenInstanceError):
                setattr(strategy, field, value)
        strategy.execute("run")
        assert fixture.calls == [("advance", "run"), ("dispatch", "run")]

    def test_batch_error_propagates_without_dispatching_stepwise(self, monkeypatch):
        fixture = ExecutionFixture()
        batch = BatchProbe(fixture)
        def fail(run_id):
            batch.calls.append(run_id)
            raise RuntimeError("batch execution interrupted")
        monkeypatch.setattr(batch, "execute", fail)
        strategy = ExecutionStrategyInteractor(fixture, fixture, fixture, ExecutionMode.BATCH, batch)
        with pytest.raises(RuntimeError, match="batch execution interrupted"):
            strategy.execute("run")
        assert batch.calls == ["run"] and fixture.calls == []


class TestExecutionStrategyIntegration:
    def test_default_path_completes_transfer_and_releases_reservation(self, tmp_path):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        try:
            assert app.client.lifecycle.execution_strategy.mode is ExecutionMode.STEPWISE
            app.client.start()
            run_id = app.client.submit_run(ProgramFixture.request())
            assert app.client.run_until_settled(run_id).status == "completed"
            assert len(factory.ports[0].executions) == 2
            assert app.client.lifecycle.operations.material.get(run_id)[2] == 2
            assert app.client.lifecycle.reservations.get(run_id).status == "released"
        finally:
            app.close()

    def test_lifecycle_uses_the_same_entry_for_an_injected_batch_executor(self, tmp_path):
        session = FakeSessionFactory()
        selector = StrategyProbeFactory()
        app = OSApplicationFactory({"fake": session}, selector).build(
            HostBuildContext(tmp_path / "os.sqlite3", "fake", None, tmp_path / "artifacts")
        )
        try:
            app.client.start()
            run_id = app.client.submit_run(ProgramFixture.request())
            before = app.client.get_run(run_id)
            assert app.client.run_until_settled(run_id) == before
            assert selector.probe.calls == [run_id]
            assert session.ports[0].executions == []
            with pytest.raises(KeyError):
                app.client.lifecycle.operations.material.get(run_id)
            assert app.client.lifecycle.reservations.get(run_id) is None
        finally:
            app.close()

    def test_terminal_batch_receipt_capability_does_not_select_execution_mode(self, tmp_path, monkeypatch):
        session = FakeSessionFactory()
        build = session.build
        def with_capability(context):
            port, snapshot, positions, capacities, mapper = build(context)
            snapshot = replace(snapshot, feedback_capabilities=ExecutionFeedbackCapabilities(("operation", "batch")))
            return port, snapshot, positions, capacities, mapper
        monkeypatch.setattr(session, "build", with_capability)
        app = session.open(tmp_path)
        try:
            app.client.start()
            run_id = app.client.submit_run(ProgramFixture.request())
            assert app.client.run_until_settled(run_id).status == "completed"
            assert app.client.lifecycle.execution_strategy.mode is ExecutionMode.STEPWISE
            assert len(session.ports[0].executions) == 2
        finally:
            app.close()
