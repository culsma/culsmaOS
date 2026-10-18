from tests.support.paths import ROOT
from pathlib import Path
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext
from tests.support.common import ProgramFixture
import pytest


class TestOfficialSimulator:

    def test_real_opentrons_api_main_chain(self, tmp_path):
        from importlib.util import find_spec

        if find_spec("opentrons") is None:
            pytest.skip("Install simulator dependencies")
        context = HostBuildContext(
            tmp_path / "os.sqlite3",
            "opentrons-simulator",
            ROOT / "examples/transfer/deck.json",
            tmp_path / "artifacts",
        )
        app = OSApplicationFactory().build(context)
        try:
            request = ProgramFixture.request()
            result = app.execute(request.plan, request.state)
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            assert len(app.host.gateway.port.session.backend.receipts) == 2
            assert all(
                (
                    r.phase == "simulated"
                    for r in app.host.gateway.port.session.backend.receipts
                )
            )
            assert sorted(
                (
                    c["volume_uL"]
                    for c in result.state.artifacts["material_state"][
                        "containers"
                    ].values()
                )
            ) == [100, 100]
        finally:
            app.close()

    def test_vendor_corruption_blocks_material_commit(self, tmp_path, monkeypatch):
        from importlib.util import find_spec

        if find_spec("opentrons") is None:
            pytest.skip("Install simulator dependencies")
        context = HostBuildContext(
            tmp_path / "os.sqlite3",
            "opentrons-simulator",
            ROOT / "examples/transfer/deck.json",
            tmp_path / "artifacts",
        )
        app = OSApplicationFactory().build(context)
        session = app.host.gateway.port.session
        interpret = session.normalizer.interpret

        def corrupt(description, payload, step_id, revision):
            payload["transfers"][0]["volume_uL"] = 999
            return interpret(description, payload, step_id, revision)

        monkeypatch.setattr(session.normalizer, "interpret", corrupt)
        try:
            result = app.execute(
                ProgramFixture.request().plan, ProgramFixture.request().state
            )
            assert (
                not result.ok
                and result.user_result["os"]["status"] == "needs_reconciliation"
            )
            assert len(session.backend.receipts) == 1
            assert app.client.lifecycle.operations.resource.occupied()
            assert (
                app.client.lifecycle.operations.material.get(
                    result.user_result["os"]["run_id"]
                )[2]
                == 0
            )
        finally:
            app.close()

    def test_real_session_restores_consumption_after_checkpoint_crash(
        self, tmp_path, monkeypatch
    ):
        from importlib.util import find_spec

        if find_spec("opentrons") is None:
            pytest.skip("Install simulator dependencies")
        context = HostBuildContext(
            tmp_path / "os.sqlite3",
            "opentrons-simulator",
            ROOT / "examples/transfer/deck.json",
            tmp_path / "artifacts",
        )
        app = OSApplicationFactory().build(context)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(run_id)

        def crash(*args):
            raise KeyboardInterrupt("after registration")

        monkeypatch.setattr(lifecycle.operations.state, "mark_ready", crash)
        with pytest.raises(KeyboardInterrupt):
            lifecycle.operations.dispatch_ready(run_id)
        assert len(app.host.gateway.port.session.backend.receipts) == 1
        app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            backend = restarted.host.gateway.port.session.backend
            assert backend.available_tips() == 95 and not backend.protocol.commands()
            assert restarted.client.get_run(run_id).status == "ready"
            assert restarted.client.run_until_settled(run_id).status == "completed"
            assert len(backend.receipts) == 1 and backend.available_tips() == 94
            assert any(
                "B1" in c for c in backend.receipts[0].commands if "Picking up" in c
            )
        finally:
            restarted.close()

