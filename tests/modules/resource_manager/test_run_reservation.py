from tests.support.paths import ROOT
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.support.common import FakeSessionFactory, ProgramFixture
from culsma_os.resource_manager.models import ResourceConflict


class TestRunReservation:
    def begin(self, app):
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        app.client.lifecycle.runs.advance_ready(run_id)
        return run_id

    def step(self, app, run_id):
        app.client.lifecycle.operations.dispatch_ready(run_id)

    def test_two_protocols_do_not_interleave(self, tmp_path):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        try:
            first = self.begin(app)
            second = app.client.submit_run(ProgramFixture.request())
            self.step(app, first)
            assert not app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.reservations.get(first).status == "active"
            blocked = app.client.run_until_settled(second)
            assert blocked.status == "ready" and blocked.error == "RUN_RESERVATION_OCCUPIED"
            assert len(factory.ports[0].executions) == 1
            assert app.client.run_until_settled(first).status == "completed"
            assert app.client.lifecycle.reservations.get(first).status == "released"
            assert app.client.run_until_settled(second).status == "completed"
            assert len(factory.ports[0].executions) == 4
        finally:
            app.close()

    def test_interrupted_run_keeps_device_reservation(self, tmp_path):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path / "first")
        run_id = self.begin(app)
        self.step(app, run_id)
        app.client.pause_run(run_id)
        app.close()
        other = factory.open(tmp_path / "other")
        restarted = factory.open(tmp_path / "first")
        try:
            other.client.start()
            waiting = other.client.submit_run(ProgramFixture.request())
            assert other.client.run_until_settled(waiting).status == "ready"
            assert factory.ports[-2].executions == []
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.get_run(run_id).status == "paused"
            restarted.client.resume_run(run_id)
            assert restarted.client.run_until_settled(run_id).status == "completed"
            assert len(factory.ports[-1].executions) == 1
            assert other.client.run_until_settled(waiting).status == "completed"
        finally:
            other.close()
            restarted.close()

    def test_unknown_attempt_retains_parent_reservation(self, tmp_path, monkeypatch):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path / "first")
        run_id = self.begin(app)
        def crash(*args):
            raise KeyboardInterrupt("after intent")
        monkeypatch.setattr(app.client.lifecycle.operations.gateway, "execute", crash)
        with pytest.raises(KeyboardInterrupt):
            self.step(app, run_id)
        app.close()
        app = factory.open(tmp_path / "first")
        other = factory.open(tmp_path / "other")
        try:
            app.client.take_over_run(run_id)
            app.client.start()
            assert app.client.get_run(run_id).status == "needs_reconciliation"
            app.client.cancel_run(run_id)
            assert app.client.lifecycle.reservations.get(run_id).status == "active"
            assert not app.client.lifecycle.reservations.finish(run_id)
            other.client.start()
            waiting = other.client.submit_run(ProgramFixture.request())
            assert other.client.run_until_settled(waiting).status == "ready"
            assert factory.ports[-1].executions == []
        finally:
            app.close()
            other.close()

    def test_distinct_cli_processes_share_station_reservation(self, tmp_path):
        root = ROOT
        code = """
import json, sys
from pathlib import Path
from tests.support.common import FakeSessionFactory, ProgramFixture
factory = FakeSessionFactory()
app = factory.open(Path(sys.argv[1]))
try:
    app.client.start()
    run_id = app.client.submit_run(ProgramFixture.request())
    if sys.argv[2] == 'hold':
        app.client.lifecycle.runs.advance_ready(run_id)
        app.client.pause_run(run_id)
    else:
        app.client.run_until_settled(run_id)
    record = app.client.get_run(run_id)
    print(json.dumps({'status': record.status, 'error': record.error, 'calls':len(factory.ports[0].executions)}), flush=True)
    if sys.argv[2] == 'hold':
        import os
        os._exit(0)  # Deliberate abrupt worker exit; no close/finally.
finally:
    app.close()
"""
        def invoke(name, action):
            process = subprocess.run([sys.executable, "-c", code, str(tmp_path/name), action],
                                     cwd=root, env=os.environ.copy(), capture_output=True, text=True, timeout=30)
            assert process.returncode == 0, process.stderr
            return json.loads(process.stdout)
        assert invoke("first-artifacts", "hold")["status"] == "paused"
        second = invoke("different-artifacts", "run")
        assert second == {"status":"ready", "error":"RUN_RESERVATION_OCCUPIED", "calls":0}

    def test_stale_run_owner_cannot_dispatch(self, tmp_path, monkeypatch):
        factory = FakeSessionFactory()
        old = factory.open(tmp_path)
        run_id = self.begin(old)
        captured = []
        gateway = old.client.lifecycle.operations.gateway
        original = gateway.execute
        def observe(plan, permit, attempt_id):
            captured.append((plan, permit, attempt_id))
            return original(plan, permit, attempt_id)
        monkeypatch.setattr(gateway, "execute", observe)
        self.step(old, run_id)
        new = factory.open(tmp_path)
        try:
            before = old.client.lifecycle.reservations.get(run_id)
            new.client.take_over_run(run_id)
            after = new.client.lifecycle.reservations.get(run_id)
            assert after.run_id == before.run_id and after.generation == before.generation + 1
            with pytest.raises(ResourceConflict, match="RUN_OWNER_STALE"):
                original(*captured[0])
            assert len(factory.ports[0].executions) == 1
            assert old.client.run_until_settled(run_id).status == "ready"
            assert len(factory.ports[0].executions) == 1
            old.client.take_over_run(run_id)
            assert old.client.lifecycle.reservations.get(run_id).generation == 3
            with pytest.raises(ResourceConflict, match="RUN_OWNER_STALE"):
                original(*captured[0])
        finally:
            new.close()
            old.close()

    def test_only_safe_terminal_run_releases_device(self, tmp_path):
        app = FakeSessionFactory().open(tmp_path)
        try:
            first = self.begin(app)
            self.step(app, first)
            assert app.client.cancel_run(first).status == "cancelled"
            reservations = app.client.lifecycle.reservations
            assert reservations.get(first).status == "released"
            proof = reservations.repository.connection.execute("SELECT proof FROM os_run_releases WHERE run_id=?", (first,)).fetchone()
            assert json.loads(proof[0])["reason"] == "verified_safe_stop"
            other = self.begin(app)
            assert reservations.get(other).status == "active"
            app.client.lifecycle.state.mark_failed(other, "pre-dispatch failure")
            app.client.run_until_settled(other)
            assert reservations.get(other).status == "released"
        finally:
            app.close()

    def test_takeover_cannot_cross_actual_dispatch(self, tmp_path, monkeypatch):
        factory = FakeSessionFactory()
        old = factory.open(tmp_path)
        run_id = self.begin(old)
        new = factory.open(tmp_path)
        original = factory.ports[0].execute
        def race(plan, attempt_id):
            with pytest.raises(ResourceConflict, match="STATION_DISPATCH_ACTIVE"):
                new.client.take_over_run(run_id)
            return original(plan, attempt_id)
        monkeypatch.setattr(factory.ports[0], "execute", race)
        try:
            self.step(old, run_id)
            new.client.take_over_run(run_id)
            assert new.client.lifecycle.reservations.get(run_id).generation == 2
        finally:
            old.close()
            new.close()

    def test_startup_does_not_steal_reservation(self, tmp_path):
        factory = FakeSessionFactory()
        old = factory.open(tmp_path)
        run_id = self.begin(old)
        before = old.client.lifecycle.reservations.get(run_id)
        old.close()
        new = factory.open(tmp_path)
        try:
            assert new.client.start() == ()
            assert new.client.lifecycle.reservations.get(run_id) == before
            assert new.client.run_until_settled(run_id).status == "waiting"
            assert factory.ports[-1].executions == []
            with pytest.raises(ResourceConflict, match="RUN_OWNER_STALE"):
                new.client.lifecycle.recovery.reconcile(run_id)
        finally:
            new.close()

    def test_distinct_run_stores_share_consumption(self, tmp_path):
        factory = FakeSessionFactory()
        first = factory.open(tmp_path/"first")
        other = factory.open(tmp_path/"other")
        other.client.start()  # Session exists before the first run consumes tips.
        try:
            request = ProgramFixture.request()
            assert first.execute(request.plan, request.state).ok
            assert factory.ports[0].remaining == 94
            assert other.execute(request.plan, request.state).ok
            assert factory.ports[1].remaining == 92
            assert other.client.lifecycle.evidence.known_consumption("fake") == {"tips":4}
            owner = other.client.lifecycle.reservations
            assert owner.usage.known("fake") == {"tips":4}
        finally:
            first.close()
            other.close()

    def test_pause_during_operation_is_preserved(self, tmp_path, monkeypatch):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        run_id = self.begin(app)
        original = factory.ports[0].execute
        def pause(plan, attempt_id):
            app.client.pause_run(run_id)
            return original(plan, attempt_id)
        monkeypatch.setattr(factory.ports[0], "execute", pause)
        try:
            assert app.client.run_until_settled(run_id).status == "paused"
            assert len(factory.ports[0].executions) == 1
            assert app.client.lifecycle.reservations.get(run_id).status == "active"
            monkeypatch.setattr(factory.ports[0], "execute", original)
            app.client.resume_run(run_id)
            assert app.client.run_until_settled(run_id).status == "completed"
        finally:
            app.close()


class TestStationUsageMigration:
    def test_local_and_shared_usage_are_unioned_by_identity(self, tmp_path):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path / 'legacy')
        request = ProgramFixture.request()
        assert app.execute(request.plan, request.state).ok
        # Model a pre-station run database with durable local evidence.
        db = app.client.lifecycle.reservations.repository.connection
        with db:
            db.execute('DELETE FROM os_station_usage')
        app.close()
        other = factory.open(tmp_path / 'new')
        request = ProgramFixture.request()
        assert other.execute(request.plan, request.state).ok
        other.close()
        app = factory.open(tmp_path / 'legacy')
        try:
            assert app.client.lifecycle.evidence.known_consumption('fake') == {'tips':4}
            app.client.start()
            assert factory.ports[-1].remaining == 92
            assert app.client.lifecycle.reservations.usage.known('fake') == {'tips':4}
            app.client.lifecycle.evidence.synchronize_device_usage('fake')
            assert app.client.lifecycle.reservations.usage.known('fake') == {'tips':4}
        finally:
            app.close()


class TestRunControl:
    def test_cli_resume_uses_saved_run_without_resubmission(self, tmp_path):
        from culsma_os.program_manager.models import HostBuildContext
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        app.client.lifecycle.runs.advance_ready(run_id)
        app.client.lifecycle.operations.dispatch_ready(run_id)
        app.client.pause_run(run_id)
        app.close()
        script = """
import sys
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.common import FakeSessionFactory
import culsma_os.cli as cli
cli.OSApplicationFactory = lambda: OSApplicationFactory({'fake': FakeSessionFactory()})
cli.CulsmaOSCLI.main(sys.argv[1:])
"""
        args = [run_id, '--host-db', str(tmp_path/'os.sqlite3'), '--driver', 'fake',
                '--artifacts-dir', str(tmp_path/'new-artifacts')]
        def invoke(action):
            return subprocess.run([sys.executable, '-c', script, action, *args],
                cwd=ROOT, env=os.environ.copy(),
                capture_output=True, text=True, timeout=30)
        status = invoke('status')
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout)['status'] == 'paused'
        result = invoke('resume')
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload['run_id'] == run_id and payload['status'] == 'completed'
        restarted = factory.open(tmp_path)
        try:
            assert restarted.host.tasks.repository.connection.execute('SELECT COUNT(*) FROM os_runs').fetchone()[0] == 1
            assert restarted.client.lifecycle.evidence.known_consumption('fake') == {'tips':2}
            assert restarted.client.lifecycle.reservations.get(run_id).generation == 2
        finally:
            restarted.close()

    def test_cancel_during_dispatch_stops_following_statement(self, tmp_path, monkeypatch):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        original = factory.ports[0].execute
        def cancel(plan, attempt_id):
            assert app.client.cancel_run(run_id).status == 'cancel_requested'
            return original(plan, attempt_id)
        monkeypatch.setattr(factory.ports[0], 'execute', cancel)
        try:
            assert app.client.run_until_settled(run_id).status == 'cancelled'
            assert len(factory.ports[0].executions) == 1
            assert app.client.lifecycle.reservations.get(run_id).status == 'released'
        finally:
            app.close()

    def test_real_simulator_reservation_and_cli_resume(self, tmp_path):
        from culsma_os.bootstrap import OSApplicationFactory
        from culsma_os.program_manager.models import HostBuildContext
        context = HostBuildContext(tmp_path/'os.sqlite3', 'opentrons-simulator',
            ROOT/'examples/transfer/deck.json', tmp_path/'artifacts')
        app = OSApplicationFactory().build(context)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        app.client.lifecycle.runs.advance_ready(run_id)
        app.client.lifecycle.operations.dispatch_ready(run_id)
        app.client.pause_run(run_id)
        app.close()
        process = subprocess.run([sys.executable, '-m', 'culsma_os.cli', 'resume', run_id,
            '--host-db', str(context.database_path), '--driver-config', str(context.config_path),
            '--artifacts-dir', str(tmp_path/'resume-artifacts')], capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stderr + process.stdout
        result = json.loads(process.stdout)
        assert result['status'] == 'completed' and result['run_id'] == run_id
        check = OSApplicationFactory().build(context)
        try:
            check.client.start()
            assert check.host.gateway.port.session.backend.available_tips() == 94
            assert check.client.lifecycle.evidence.known_consumption('opentrons') == {'tips':2}
            assert check.client.lifecycle.reservations.get(run_id).status == 'released'
        finally:
            check.close()

    def test_second_protocol_in_same_real_session_preserves_tips(self, tmp_path):
        from culsma_os.bootstrap import OSApplicationFactory
        from culsma_os.program_manager.models import HostBuildContext
        context = HostBuildContext(tmp_path/'os.sqlite3', 'opentrons-simulator',
            ROOT/'examples/transfer/deck.json', tmp_path/'artifacts')
        app = OSApplicationFactory().build(context)
        try:
            request = ProgramFixture.request()
            assert app.execute(request.plan, request.state).ok
            request = ProgramFixture.request()
            assert app.execute(request.plan, request.state).ok
            backend = app.host.gateway.port.session.backend
            assert backend.available_tips() == 92 and len(backend.receipts) == 4
        finally:
            app.close()


class TestTerminalReservationRecovery:
    def test_completed_checkpoint_before_parent_release_can_be_finished(self, tmp_path, monkeypatch):
        from culsma_os.bootstrap import OSApplicationFactory
        from culsma_os.program_manager.models import HostBuildContext, RunControlRequest
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        def crash(*args):
            raise KeyboardInterrupt('completed checkpoint saved, parent not released')
        monkeypatch.setattr(app.client.lifecycle.reservations, 'finish', crash)
        with pytest.raises(KeyboardInterrupt):
            app.client.run_until_settled(run_id)
        assert app.client.get_run(run_id).status == 'finalizing'
        assert app.client.lifecycle.reservations.get(run_id).status == 'active'
        app.close()
        controller = OSApplicationFactory({'fake':factory}).build_run_controller()
        context = HostBuildContext(tmp_path/'os.sqlite3', 'fake', None, tmp_path/'new-artifacts')
        assert controller.execute(RunControlRequest('resume', run_id, context))['ok']
        app = factory.open(tmp_path)
        try:
            assert app.client.lifecycle.reservations.get(run_id).status == 'released'
            assert factory.ports[-2].executions == []
        finally:
            app.close()

    def test_safe_release_before_cancelled_checkpoint_is_repaired(self, tmp_path, monkeypatch):
        from culsma_os.bootstrap import OSApplicationFactory
        from culsma_os.program_manager.models import HostBuildContext, RunControlRequest
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        app.client.lifecycle.runs.advance_ready(run_id)
        app.client.lifecycle.operations.dispatch_ready(run_id)
        def crash(*args):
            raise KeyboardInterrupt('parent released, cancellation not checkpointed')
        monkeypatch.setattr(app.client.lifecycle.state, 'complete_finalization', crash)
        with pytest.raises(KeyboardInterrupt):
            app.client.cancel_run(run_id)
        assert app.client.get_run(run_id).status == 'finalizing'
        assert app.client.lifecycle.reservations.get(run_id).status == 'released'
        app.close()
        context = HostBuildContext(tmp_path/'os.sqlite3', 'fake', None, tmp_path/'new-artifacts')
        result = OSApplicationFactory({'fake':factory}).build_run_controller().execute(RunControlRequest('resume', run_id, context))
        assert result['status'] == 'cancelled' and not result['ok']
        assert factory.ports[-1].executions == []

