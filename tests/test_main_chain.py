from dataclasses import replace
import json
import sqlite3
import pytest
from .support import ProgramFixture, FakeSessionFactory
from culsma_os.resource_manager.models import ExecutionPermit, ResourceConflict


class TestMainChain:

    def test_simulation_ledger_and_conservation(self, tmp_path):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        try:
            request = ProgramFixture.request()
            result = app.execute(request.plan, request.state)
            assert result.ok and sorted(
                (
                    c["volume_uL"]
                    for c in result.state.artifacts["material_state"][
                        "containers"
                    ].values()
                )
            ) == [100, 100]
            assert len(factory.ports[0].executions) == 2
            db = sqlite3.connect(tmp_path / "os.sqlite3")
            assert db.execute("SELECT COUNT(*) FROM os_evidence").fetchone()[0] == 2
            assert (
                db.execute("SELECT COUNT(*) FROM os_material_changes").fetchone()[0]
                == 2
            )
            mode, state, revision = db.execute(
                "SELECT mode,state,version FROM os_material"
            ).fetchone()
            assert mode == "simulation" and revision == 2
            assert json.loads(state) == result.state.artifacts["material_state"]
            assert (
                db.execute("SELECT COUNT(*) FROM os_resource_locks").fetchone()[0] == 0
            )
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM os_run_outbox WHERE published=0"
                ).fetchone()[0]
                == 0
            )
            assert db.execute("SELECT COUNT(*) FROM os_run_history").fetchone()[0] >= 5
            db.close()
        finally:
            app.close()

    def test_duplicate_evidence_and_registration(self, tmp_path):
        app = FakeSessionFactory().open(tmp_path)
        try:
            app.client.start()
            run_id = app.client.submit_run(ProgramFixture.request())
            lifecycle = app.client.lifecycle
            record = lifecycle.runs.advance_ready(run_id)
            pending = lifecycle.operations.execution.pending(run_id)
            lifecycle.operations.dispatch_ready(run_id)
            evidence = lifecycle.operations.evidence.find_evidence(pending.effect_id)
            lifecycle.operations.evidence.ingest(evidence)
            first = lifecycle.operations.material.reconcile(pending, evidence)
            second = lifecycle.operations.material.reconcile(pending, evidence)
            assert first == second
            assert lifecycle.operations.material.get(run_id)[2] == 1
            with pytest.raises(ValueError):
                lifecycle.operations.evidence.ingest(
                    replace(evidence, payload={"different": True})
                )
        finally:
            app.close()

    def test_crash_after_intent_never_replays(self, tmp_path, monkeypatch):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(run_id)

        def crash(*args):
            raise KeyboardInterrupt("process crash after intent")

        monkeypatch.setattr(lifecycle.operations.gateway, "execute", crash)
        with pytest.raises(KeyboardInterrupt):
            lifecycle.operations.dispatch_ready(run_id)
        app.close()
        restarted = factory.open(tmp_path)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.get_run(run_id).status == "needs_reconciliation"
            restarted.client.run_until_settled(run_id)
            assert factory.ports[-1].executions == []
            assert restarted.client.lifecycle.operations.resource.occupied()
        finally:
            restarted.close()

    def test_restart_after_registration_resumes_without_execute(
        self, tmp_path, monkeypatch
    ):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(run_id)

        def crash(*args):
            raise KeyboardInterrupt("checkpoint save crash")

        monkeypatch.setattr(lifecycle.operations.state, "mark_ready", crash)
        with pytest.raises(KeyboardInterrupt):
            lifecycle.operations.dispatch_ready(run_id)
        assert len(factory.ports[0].executions) == 1
        app.close()
        restarted = factory.open(tmp_path)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.get_run(run_id).status == "ready"
            assert factory.ports[-1].executions == []
            assert factory.ports[-1].remaining == 95
            restarted.client.run_until_settled(run_id)
            assert restarted.client.get_run(run_id).status == "completed"
            assert len(factory.ports[-1].executions) == 1
            assert restarted.client.lifecycle.operations.material.get(run_id)[2] == 2
        finally:
            restarted.close()

    def test_stale_plan_and_resource_conflict(self, tmp_path, monkeypatch):
        app = FakeSessionFactory().open(tmp_path)
        app.client.start()
        try:
            run_id = app.client.submit_run(ProgramFixture.request())
            lifecycle = app.client.lifecycle
            lifecycle.runs.advance_ready(run_id)
            monkeypatch.setattr(
                lifecycle.operations.space,
                "validate_snapshot",
                lambda *a: (_ for _ in ()).throw(ValueError("WORKSPACE_LAYOUT_STALE")),
            )
            lifecycle.operations.dispatch_ready(run_id)
            assert app.client.get_run(run_id).status == "finalizing"
            assert app.client.get_run(run_id).body_outcome == "failed"
            assert app.client.run_until_settled(run_id).status == "failed"
            assert not app.host.gateway.port.executions
            assert not lifecycle.operations.resource.occupied()
            resource = lifecycle.operations.resource.repository
            first = ExecutionPermit("a", "attempt-a", ("gantry",))
            second = ExecutionPermit("b", "attempt-b", ("gantry",))
            resource.acquire(first)
            with pytest.raises(ResourceConflict):
                resource.acquire(second)
            resource.authorize(first)
            with pytest.raises(ResourceConflict):
                resource.authorize(first)
        finally:
            app.close()

    def test_unknown_and_mismatched_feedback_blocks_continuation(
        self, tmp_path, monkeypatch
    ):
        app = FakeSessionFactory().open(tmp_path)
        app.client.start()
        try:
            run_id = app.client.submit_run(ProgramFixture.request())
            lifecycle = app.client.lifecycle
            lifecycle.runs.advance_ready(run_id)
            execute = app.host.gateway.port.execute

            def wrong(plan, attempt_id):
                payload = execute(plan, attempt_id)
                payload["step_id"] = "wrong-effect"
                return payload

            monkeypatch.setattr(app.host.gateway.port, "execute", wrong)
            lifecycle.operations.dispatch_ready(run_id)
            assert app.client.get_run(run_id).status == "needs_reconciliation"
            assert lifecycle.operations.resource.occupied()
            assert lifecycle.operations.material.get(run_id)[2] == 0
            app.client.run_until_settled(run_id)
            assert len(app.host.gateway.port.executions) == 1
        finally:
            app.close()
