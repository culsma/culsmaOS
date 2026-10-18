"""Whole-protocol acceptance using official simulated modules and durable OS state."""
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
from culsma_os.program_manager.models import RunRequest
from .test_transfer_matrix import TransferMatrixFixture

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/framework/combined-processing"


class FrameworkProtocolFixture:
    def build(self, directory, source=None):
        source = source if source is not None else (EXAMPLE / "protocol.culs").read_text()
        fixture = TransferMatrixFixture()
        plan = fixture.compile(source, directory)
        config = json.loads((EXAMPLE / "deck.json").read_text())
        if "let collateral" in source:
            # Only this variant inserts an allocation, all typed bindings stay explicit.
            allocations = [s for p in plan.plans for s in p.steps if s.op == "AllocContainer"]
            addresses = [("shaking", "A1"), ("heated", "A1"), ("heated", "B1"),
                         ("captured", "A1"), ("tubes", "A1"), ("tubes", "A2")]
            assert len(allocations) == len(addresses)
            config["bindings"] = {s.step_id: {"labware": labware, "well": well}
                                  for s, (labware, well) in zip(allocations, addresses)}
        def configure(raw):
            raw.clear()
            raw.update(deepcopy(config))
        context = fixture.context(directory, plan, config_mutation=configure)
        return plan, context, OSApplicationFactory().build(context)

    def waiting(self, app, plan, operation):
        app.client.start()
        identity = app.client.submit_run(RunRequest(plan, init_state(plan)))
        lifecycle = app.client.lifecycle
        for _ in range(8):
            lifecycle.runs.advance_ready(identity)
            pending = app.client.execution.pending(identity)
            assert pending is not None, app.client.get_run(identity)
            if pending.prepared.runtime_step.op == operation:
                return identity, pending
            lifecycle.operations.dispatch_ready(identity)
        raise AssertionError(f"Missing operation {operation}")

    def assert_material(self, app, identity, plan):
        expected = json.loads((EXAMPLE / "expected.json").read_text())
        mode, material, version = app.host.material.get(identity)
        baseline = run(plan, StubDriver(), init_state(plan))
        assert baseline.ok
        assert material == baseline.state.artifacts["material_state"]
        by_allocation = {c["metadata"]["allocation_step_id"]: c for c in material["containers"].values()}
        containers = [by_allocation[identity] for identity in expected["allocation_step_ids"]]
        assert [c["volume_uL"] for c in containers] == expected["volumes_uL"]
        assert [{k: v for k, v in c["components"].items() if v} for c in containers] == expected["components"]
        assert mode == expected["mode"] and version == expected["material_version"]
        return expected

    def assert_released(self, app, identity):
        assert app.client.lifecycle.reservations.get(identity).status == "released"
        assert not app.client.lifecycle.operations.resource.occupied()
        assert not app.client.lifecycle.conditions.outstanding(identity)


class TestFrameworkProtocol:
    def test_normal_protocol(self, tmp_path):
        fixture = FrameworkProtocolFixture()
        plan, context, app = fixture.build(tmp_path)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            identity = result.user_result["os"]["run_id"]
            expected = fixture.assert_material(app, identity, plan)
            fixture.assert_released(app, identity)
            session = app.host.gateway.port.session
            assert len(session.backend.receipts) == expected["transfer_receipts"]
            assert len(session.agitation.receipts) == expected["agitation_receipts"]
            assert len(session.thermal.receipts) == expected["thermal_receipts"]
            assert [r.payload["operation_kind"] for r in session.magnetic.receipts] == expected["magnetic_operations"]
            assert session.backend.available_tips() == expected["available_tips"]
            assert not session.magnetic.held
            attempts = app.client.lifecycle.evidence.attempts_for_run(identity)
            assert len(attempts) == expected["language_effects"] + expected["os_system_effects"]
            for attempt in attempts:
                evidence = app.client.lifecycle.evidence.find_evidence(attempt.effect_id)
                assert evidence.outcome == "completed" and evidence.mode == "simulation"
                system = attempt.context["description"].get("system_effect") == "condition_release"
                assert app.host.material.registered(attempt.effect_id) is not system
            commands = session.backend.protocol.commands()
            assert commands[-1] == "Disengaging Magnetic Module"
            assert next(i for i, c in enumerate(commands) if "Deactivating Shaker" in c) < next(i for i, c in enumerate(commands) if "Setting Temperature" in c)
            assert len(app.client.execution.host.codec.loads(app.client.get_run(identity).checkpoint)["confirmed"]) == expected["language_effects"]
        finally:
            app.close()

    @pytest.mark.parametrize("entry", ["culsma_os.cli", "culsma.cli"])
    def test_both_cli_entries(self, tmp_path, entry):
        plan, context, app = FrameworkProtocolFixture().build(tmp_path)
        app.close()
        artifacts = tmp_path / "cli-artifacts"
        process = subprocess.run([sys.executable, "-m", entry, "run", str(tmp_path / "protocol.culs"),
            "--driver", "opentrons-simulator", "--driver-config", str(context.config_path),
            "--artifacts-dir", str(artifacts)], capture_output=True, text=True, timeout=90)
        assert process.returncode == 0, process.stdout + process.stderr
        result = json.loads((artifacts / "run.json").read_text())
        assert result["ok"] and result["user_result"]["os"]["status"] == "completed"

    def test_static_rejection_before_actions(self, tmp_path):
        source = (EXAMPLE / "protocol.culs").read_text().replace("magnetic_program(duration=5min)", "centrifuge_program(drive=1000g)")
        plan, context, app = FrameworkProtocolFixture().build(tmp_path, source)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok
            assert "HOST_OPERATION_UNSUPPORTED" in str(result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:
            app.close()

    @pytest.mark.parametrize("kind", ["rate", "collateral"])
    def test_preflight_rejection_prevents_completed_prefix(self, tmp_path, kind):
        source = (EXAMPLE / "protocol.culs").read_text()
        source = source.replace("500rpm", "3001rpm") if kind == "rate" else source.replace("let heated = heating_plate[A1];", "let heated = heating_plate[A1]; let collateral = heating_plate[B1];")
        plan, context, app = FrameworkProtocolFixture().build(tmp_path, source)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result["os"]["status"] == "failed"
            assert "PROCESSING_" in str(result.diagnostics)
            identity = result.user_result["os"]["run_id"]
            with pytest.raises(KeyError):
                app.host.material.get(identity)
            session = app.host.gateway.port.session
            assert not session.backend.protocol.commands() and not session.backend.receipts
            assert result.user_result["os"]["preflight"]["status"] == "rejected"
            assert not session.thermal.receipts and not session.magnetic.receipts
            FrameworkProtocolFixture().assert_released(app, identity)
        finally:
            app.close()

    @pytest.mark.parametrize("operation,version,transfers", [("agit", 1, 1), ("env_hold", 3, 2)])
    def test_runtime_rejection_keeps_completed_prefix(self, tmp_path, monkeypatch, operation, version, transfers):
        plan, context, app = FrameworkProtocolFixture().build(tmp_path)
        processing = app.client.lifecycle.operations.planners[operation]
        original = processing.prepare
        def live_rejection(request):
            if request.pending.prepared.runtime_step.op == operation:
                raise ValueError("PROCESSING_LIVE_CONFIGURATION_REJECTED")
            return original(request)
        monkeypatch.setattr(processing, "prepare", live_rejection)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result["os"]["preflight"]["status"] == "passed"
            assert "PROCESSING_LIVE_CONFIGURATION_REJECTED" in str(result.diagnostics)
            identity = result.user_result["os"]["run_id"]
            assert app.host.material.get(identity)[2] == version
            assert len(app.host.gateway.port.session.backend.receipts) == transfers
            FrameworkProtocolFixture().assert_released(app, identity)
        finally:
            app.close()

    @pytest.mark.parametrize("phase,version,transfers", [
        ("agitation", 1, 1), ("thermal", 3, 2), ("separation", 5, 3),
        ("flowthrough", 6, 3), ("release", 7, 4)])
    def test_unknown_effect_blocks_downstream(self, tmp_path, monkeypatch, phase, version, transfers):
        plan, context, app = FrameworkProtocolFixture().build(tmp_path)
        session = app.host.gateway.port.session
        obj, method = {
            "agitation": (session.backend.modules["shaker"], "set_and_wait_for_shake_speed"),
            "thermal": (session.backend.modules["heater"], "set_temperature"),
            "separation": (session.backend.modules["magnet"], "engage"),
            "flowthrough": (session.backend.pipette, "aspirate"),
            "release": (session.backend.modules["magnet"], "disengage"),
        }[phase]
        original = getattr(obj, method)
        def unknown(*args, **kwargs):
            value = original(*args, **kwargs)
            if phase != "flowthrough" or session.magnetic.held:
                raise RuntimeError("injected after command returned")
            return value
        monkeypatch.setattr(obj, method, unknown)
        try:
            result = app.execute(plan, init_state(plan))
            identity = result.user_result["os"]["run_id"]
            assert not result.ok and result.user_result["os"]["status"] == "needs_reconciliation"
            assert app.host.material.get(identity)[2] == version
            assert len(session.backend.receipts) == transfers
            assert app.client.lifecycle.reservations.get(identity).status == "active"
            assert app.client.lifecycle.operations.resource.occupied()
            attempts = app.client.lifecycle.evidence.attempts_for_run(identity)
            unknowns = [a for a in attempts if app.client.lifecycle.evidence.find_evidence(a.effect_id).outcome == "unknown"]
            assert len(unknowns) == 1
            assert not app.host.material.registered(unknowns[0].effect_id)
            if phase in {"agitation", "thermal"}:
                assert not session.magnetic.receipts
            if phase == "agitation":
                assert not session.thermal.receipts
            if phase != "release":
                assert "Disengaging Magnetic Module" not in session.backend.protocol.commands()
                assert app.host.material.uncertainties(identity)
            else:
                assert not app.host.material.uncertainties(identity)
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == "needs_reconciliation"
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.host.material.get(identity)[2] == version
        finally:
            restarted.close()

    @pytest.mark.parametrize("operation", ["agit", "env_hold"])
    @pytest.mark.parametrize("point", ["registration", "checkpoint"])
    def test_completed_processing_recovers_without_repetition(self, tmp_path, monkeypatch, operation, point):
        fixture = FrameworkProtocolFixture()
        plan, context, app = fixture.build(tmp_path)
        identity, pending = fixture.waiting(app, plan, operation)
        ops = app.client.lifecycle.operations
        def crash(*args, **kwargs):
            raise KeyboardInterrupt("after persisted processing evidence")
        monkeypatch.setattr(ops.material if point == "registration" else ops.state,
                            "reconcile" if point == "registration" else "mark_ready", crash)
        try:
            with pytest.raises(KeyboardInterrupt):
                ops.dispatch_ready(identity)
            assert ops.evidence.find_evidence(pending.effect_id).outcome == "completed"
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == "completed"
            fixture.assert_material(restarted, identity, plan)
            fixture.assert_released(restarted, identity)
            session = restarted.host.gateway.port.session
            assert not session.agitation.receipts
            if operation == "env_hold":
                assert not session.thermal.receipts
            assert session.backend.available_tips() == 92
        finally:
            restarted.close()

    def test_restart_never_reconstructs_field(self, tmp_path, monkeypatch):
        fixture = FrameworkProtocolFixture()
        plan, context, app = fixture.build(tmp_path)
        identity, pending = fixture.waiting(app, plan, "sep")
        def crash(*args, **kwargs):
            raise KeyboardInterrupt("after persisted separation evidence")
        monkeypatch.setattr(app.host.material, "reconcile", crash)
        try:
            with pytest.raises(KeyboardInterrupt):
                app.client.lifecycle.operations.dispatch_ready(identity)
            assert app.client.lifecycle.evidence.find_evidence(pending.effect_id).outcome == "completed"
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status in {"failed", "needs_reconciliation"}
            assert restarted.host.material.get(identity)[2] == 6
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.reservations.get(identity).status == "active"
        finally:
            restarted.close()

    def test_completed_release_recovers_without_actions(self, tmp_path, monkeypatch):
        fixture = FrameworkProtocolFixture()
        plan, context, app = fixture.build(tmp_path)
        resource = app.client.lifecycle.operations.resource
        original = resource.settle
        def crash(attempt_id, evidence):
            if evidence.payload.get("operation_kind") == "magnetic_release":
                raise KeyboardInterrupt("after persisted release evidence")
            return original(attempt_id, evidence)
        monkeypatch.setattr(resource, "settle", crash)
        try:
            with pytest.raises(KeyboardInterrupt):
                app.execute(plan, init_state(plan))
            identity = next(iter(app.client.lifecycle.runs.session_runs))
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == "completed"
            fixture.assert_material(restarted, identity, plan)
            fixture.assert_released(restarted, identity)
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally:
            restarted.close()
