from tests.support.paths import ROOT
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import ast
import sqlite3
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext, RunControlRequest
from culsma_os.program_manager.repositories.runs import SqliteTaskRepository
from culsma_os.program_manager.interactors.run_state import RunStateInteractor
from tests.support.common import FakeSessionFactory, ProgramFixture


class TestRunFinalization:
    def begin(self, directory):
        factory = FakeSessionFactory()
        app = factory.open(directory)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        return factory, app, run_id

    def status(self, directory, run_id, monkeypatch, driver="fake", config=None):
        context = HostBuildContext(directory / "os.sqlite3", driver, config, directory / "status-artifacts")
        def forbidden(*args, **kwargs):
            raise AssertionError("Read-only status must not build a device session")
        with monkeypatch.context() as guard:
            guard.setattr(OSApplicationFactory, "build", forbidden)
            inspector = OSApplicationFactory().build_run_inspector(context)
            try:
                return inspector.execute(RunControlRequest("status", run_id, context))
            finally:
                inspector.close()

    def test_status_before_cleanup(self, tmp_path, monkeypatch):
        factory, app, run_id = self.begin(tmp_path)
        def crash(*args):
            raise KeyboardInterrupt("before cleanup")
        monkeypatch.setattr(app.client.lifecycle.finalization, "finalize", crash)
        try:
            with pytest.raises(KeyboardInterrupt):
                app.client.run_until_settled(run_id)
            record = app.client.get_run(run_id)
            assert (record.status, record.body_outcome) == ("finalizing", "succeeded")
            assert not app.client.result(run_id).ok
            response = self.status(tmp_path, run_id, monkeypatch)
            assert response["status"] == "finalizing" and not response["ok"]
            assert response["result"]["os"]["body_outcome"] == "succeeded"
            assert app.client.lifecycle.reservations.get(run_id).status == "active"
            assert len(factory.ports[0].executions) == 2
        finally:
            app.close()

    @pytest.mark.parametrize("point", ["before-release", "after-release", "before-terminal-save"])
    def test_crash_windows(self, tmp_path, monkeypatch, point):
        factory, app, run_id = self.begin(tmp_path)
        lifecycle = app.client.lifecycle
        finish = lifecycle.reservations.finish
        def crash(*args):
            if point == "after-release":
                assert finish(*args)
            raise KeyboardInterrupt(point)
        target, method = (lifecycle.state, "complete_finalization") if point == "before-terminal-save" else (lifecycle.reservations, "finish")
        monkeypatch.setattr(target, method, crash)
        try:
            with pytest.raises(KeyboardInterrupt):
                app.client.run_until_settled(run_id)
            assert self.status(tmp_path, run_id, monkeypatch)["ok"] is False
            assert app.client.get_run(run_id).body_outcome == "succeeded"
        finally:
            app.close()
        restarted = factory.open(tmp_path)
        try:
            if point != "before-release":
                def forbidden(*args):
                    raise AssertionError("A released reservation must never be reacquired or dispatched")
                for target, methods in [(restarted.client.lifecycle.reservations, ("acquire", "take_over")),
                        (restarted.host.gateway.port, ("check_ready", "prepare", "execute"))]:
                    for method in methods:
                        monkeypatch.setattr(target, method, forbidden)
                # Startup must see finalizing even though its reservation is released.
                restarted.client.start()
            else:
                restarted.client.take_over_run(run_id)
                restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status == "completed"
            assert restarted.client.get_run(run_id).body_outcome == "succeeded"
            assert restarted.client.lifecycle.reservations.get(run_id).status == "released"
            assert factory.ports[-1].executions == []
        finally:
            restarted.close()

    def test_failed_body_cleanup(self, tmp_path, monkeypatch):
        _, app, run_id = self.begin(tmp_path)
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(run_id)
        lifecycle.state.mark_failed(run_id, "ORIGINAL_BODY_FAILURE")
        try:
            with monkeypatch.context() as guard:
                def fail(*args):
                    raise ValueError("cleanup failed")
                guard.setattr(lifecycle.conditions, "finish", fail)
                record = app.client.run_until_settled(run_id)
                assert record.status == "needs_reconciliation" and record.body_outcome == "failed"
                assert record.body_error == "ORIGINAL_BODY_FAILURE"
                assert lifecycle.reservations.get(run_id).status == "active"
            record = app.client.run_until_settled(run_id)
            assert record.status == "failed" and record.body_outcome == "failed"
            assert record.error == record.body_error == "ORIGINAL_BODY_FAILURE"
            assert lifecycle.reservations.get(run_id).status == "released"
            assert not app.client.result(run_id).ok
        finally:
            app.close()

    def test_cancelled_body_cleanup(self, tmp_path, monkeypatch):
        _, app, run_id = self.begin(tmp_path)
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(run_id)
        lifecycle.operations.dispatch_ready(run_id)
        try:
            with monkeypatch.context() as guard:
                def fail(*args):
                    raise ValueError("cleanup failed")
                guard.setattr(lifecycle.conditions, "finish", fail)
                record = app.client.cancel_run(run_id)
                assert record.status == "needs_reconciliation" and record.body_outcome == "cancelled"
            record = app.client.run_until_settled(run_id)
            assert record.status == "cancelled" and record.body_outcome == "cancelled"
            assert not app.client.result(run_id).ok
        finally:
            app.close()

    def test_crash_before_body_checkpoint_commit(self, tmp_path, monkeypatch):
        factory, app, run_id = self.begin(tmp_path)
        def crash(*args, **kwargs):
            raise KeyboardInterrupt("body checkpoint not saved")
        monkeypatch.setattr(app.client.lifecycle.state, "begin_finalization", crash)
        try:
            with pytest.raises(KeyboardInterrupt):
                app.client.run_until_settled(run_id)
            assert app.client.get_run(run_id).status == "ready"
            assert len(factory.ports[0].executions) == 2
        finally:
            app.close()
        restarted = factory.open(tmp_path)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status == "completed"
            assert factory.ports[-1].executions == []
        finally:
            restarted.close()

    def test_orphan_permit_prevents_terminal_release(self, tmp_path):
        from culsma_os.transfer_engine.models import TransferRequest
        factory, app, run_id = self.begin(tmp_path)
        lifecycle = app.client.lifecycle
        try:
            lifecycle.runs.advance_ready(run_id)
            ops = lifecycle.operations
            plan = ops.transfer.prepare(TransferRequest(run_id, ops.execution.pending(run_id)))
            ops.resource.acquire(plan, "prepared-without-intent")
            lifecycle.state.mark_failed(run_id, "PREPARATION_INTERRUPTED")
            record = app.client.run_until_settled(run_id)
            assert record.status == "needs_reconciliation" and record.body_outcome == "failed"
            assert record.error == "FINALIZATION_PERMITS_UNSETTLED"
            assert lifecycle.reservations.get(run_id).status == "active"
            assert ops.resource.occupied() and factory.ports[0].executions == []
        finally:
            app.close()

    def test_no_device_cancel(self, tmp_path):
        factory, app, run_id = self.begin(tmp_path)
        try:
            record = app.client.cancel_run(run_id)
            assert record.status == "cancelled" and record.body_outcome == "cancelled"
            assert app.client.lifecycle.reservations.get(run_id) is None
            assert factory.ports[0].executions == []
        finally:
            app.close()

    def capture_proof(self, app, run_id, monkeypatch):
        found = []
        def crash(identity, proof):
            found.append(proof)
            raise KeyboardInterrupt("terminal save interrupted")
        monkeypatch.setattr(app.client.lifecycle.state, "complete_finalization", crash)
        with pytest.raises(KeyboardInterrupt):
            app.client.run_until_settled(run_id)
        return found[0]

    @pytest.mark.parametrize("field", ["run", "revision", "outcome", "evidence", "release"])
    def test_completion_requires_matching_proof(self, tmp_path, monkeypatch, field):
        _, app, run_id = self.begin(tmp_path)
        state = app.client.lifecycle.state
        complete = state.complete_finalization
        try:
            proof = self.capture_proof(app, run_id, monkeypatch)
            changes = {"run": {"run_id": "another-run"}, "revision": {"revision": proof.revision-1},
                "outcome": {"body_outcome": "failed"}, "evidence": {"evidence_ids": ()},
                "release": {"release": replace(proof.release, run_id="another-run")}}
            with pytest.raises(ValueError, match="RUN_FINALIZATION_PROOF_INVALID"):
                complete(run_id, replace(proof, **changes[field]))
            assert app.client.get_run(run_id).status == "finalizing"
        finally:
            app.close()

    def test_revision_conflict(self, tmp_path, monkeypatch):
        _, app, run_id = self.begin(tmp_path)
        state = app.client.lifecycle.state
        complete = state.complete_finalization
        try:
            proof = self.capture_proof(app, run_id, monkeypatch)
            state.mark_reconciliation_required(run_id, "NEWER_STATE")
            with pytest.raises(ValueError, match="RUN_FINALIZATION_PROOF_INVALID"):
                complete(run_id, proof)
            monkeypatch.setattr(state, "complete_finalization", complete)
            assert app.client.run_until_settled(run_id).status == "completed"
        finally:
            app.close()

    @pytest.mark.parametrize("status,outcome", [("completed", "succeeded"), ("failed", "failed"), ("cancelled", "cancelled")])
    def test_legacy_terminal_requires_verification(self, status, outcome):
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE TABLE os_runs(run_id TEXT PRIMARY KEY,status TEXT,checkpoint TEXT,revision INTEGER,error TEXT)")
            connection.execute("INSERT INTO os_runs VALUES(?,?,?,?,?)", ("legacy", status, "checkpoint", 3, None))
            repository = SqliteTaskRepository(connection)
            state = RunStateInteractor(repository, None, None)
            assert repository.get("legacy").status == status
            record = state.get("legacy")
            assert record.status == "finalizing" and record.body_outcome == outcome
            assert record.revision == 3 and repository.get("legacy").body_outcome is None
            assert [r.run_id for r in repository.unfinished()] == ["legacy"]

    def test_legacy_terminal_event_not_published_early(self):
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE TABLE os_runs(run_id TEXT PRIMARY KEY,status TEXT,checkpoint TEXT,revision INTEGER,error TEXT)")
            connection.execute("INSERT INTO os_runs VALUES(?,?,?,?,?)", ("legacy", "completed", "checkpoint", 3, None))
            repository = SqliteTaskRepository(connection)
            connection.execute("INSERT INTO os_run_outbox VALUES(?,?,?,?,?)", ("old-success", "legacy", "completed", 3, 0))
            events = []
            state = RunStateInteractor(repository, None, SimpleNamespace(record_run_event=events.append))
            state.publish_pending_events()
            assert events == [] and len(repository.pending_events()) == 1

    def test_run_state_single_writer(self):
        root = ROOT / "src/culsma_os"
        for path in (root / "program_manager/interactors").glob("*.py"):
            tree = ast.parse(path.read_text())
            transitions = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "replace"
                and any(k.arg in {"status", "body_outcome"} for k in node.keywords)]
            if transitions:
                assert path.name == "run_state.py", path
        for path in root.rglob("*.py"):
            if path.name != "run_state.py":
                assert "self.tasks.save(" not in path.read_text(), path


class TestMagneticFinalization:
    @pytest.mark.parametrize("point", ["before-cleanup", "before-execute", "after-device", "after-evidence", "after-reservation-release"])
    def test_read_only_status_at_crash_windows(self, tmp_path, monkeypatch, point):
        from tests.support.processing_engine.processing_magnetic import MagneticFixture
        from culsma.runtime.state import init_state
        plan, context, app = MagneticFixture().build(tmp_path)
        lifecycle = app.client.lifecycle
        original = app.host.gateway.execute
        def execute(prepared, permit, attempt):
            if prepared.description.get("system_effect") == "condition_release":
                if point == "after-device":
                    original(prepared, permit, attempt)
                raise KeyboardInterrupt(point)
            return original(prepared, permit, attempt)
        def before_cleanup(*args):
            raise KeyboardInterrupt(point)
        settle = lifecycle.operations.resource.settle
        def after_evidence(attempt, fact):
            if fact.payload.get("operation_kind") == "magnetic_release":
                raise KeyboardInterrupt(point)
            return settle(attempt, fact)
        finish = lifecycle.reservations.finish
        def after_release(identity):
            assert finish(identity)
            raise KeyboardInterrupt(point)
        if point == "before-cleanup":
            monkeypatch.setattr(lifecycle.conditions, "finish", before_cleanup)
        elif point in {"before-execute", "after-device"}:
            monkeypatch.setattr(app.host.gateway, "execute", execute)
        elif point == "after-evidence":
            monkeypatch.setattr(lifecycle.operations.resource, "settle", after_evidence)
        else:
            monkeypatch.setattr(lifecycle.reservations, "finish", after_release)
        try:
            with pytest.raises(KeyboardInterrupt):
                app.execute(plan, init_state(plan))
            run_id = next(iter(lifecycle.runs.session_runs))
            assert app.client.get_run(run_id).status == "finalizing"
            response = TestRunFinalization().status(tmp_path, run_id, monkeypatch,
                context.driver_name, context.config_path)
            assert response["status"] == "finalizing" and not response["ok"]
            assert response["body_outcome"] == "succeeded"
            assert not app.client.result(run_id).ok
            version = app.host.material.get(run_id)[2]
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            record = restarted.client.run_until_settled(run_id)
            assert record.status == ("completed" if point in {"after-evidence", "after-reservation-release"} else "needs_reconciliation")
            assert record.body_outcome == "succeeded"
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.host.material.get(run_id)[2] == version
            if record.status == "needs_reconciliation":
                assert restarted.client.lifecycle.reservations.get(run_id).status == "active"
        finally:
            restarted.close()

