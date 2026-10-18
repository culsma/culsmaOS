"""Whole-program admission uses projected language state, never execution evidence."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import ast
import pytest
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma.driver.stub import StubDriver
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest, PendingEffectGroup
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.preflight import ProgramPreflightInteractor
from .test_processing_centrifuge_separation import SeparationContractFixture, BASE, SEP, SOURCE
from .support import FakeSessionFactory, ProgramFixture
from .test_transfer_matrix import TransferMatrixFixture


def test_late_configuration_error_prevents_earlier_motion(tmp_path):
    fixture = SeparationContractFixture(profile=None)
    source = BASE + "d << [s:10uL];" + SEP + "return s;"
    plan, _, app = fixture.open(tmp_path, source)
    try:
        result = app.execute(plan, init_state(plan))
        assert not result.ok and result.user_result["os"]["status"] == "failed"
        report = result.user_result["os"]["preflight"]
        assert report["status"] == "rejected" and report["checked_effects"] == 2
        assert report["projected_path_complete"]
        assert any("PROCESSING_METHOD_PROFILE_REQUIRED" in d["message"] for d in report["diagnostics"])
        assert not fixture.port.executions and not fixture.port.transfers and not fixture.port.processing
        connection = app.host.material.repository.connection
        for table in ("os_attempts", "os_evidence"):
            # A failed admission must not manufacture hardware attempts or material registration.
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert "registered_material" not in result.user_result["os"]
    finally:
        app.close()


def test_collects_errors_without_device_or_storage_calls(tmp_path, monkeypatch):
    fixture = SeparationContractFixture(profile=None)
    source = BASE + SEP + "agit(sample=s,mode=shake,motion=orbital,rate=500rpm,duration=1s);"
    plan, _, app = fixture.open(tmp_path, source)
    host = app.client.execution.host
    def forbidden(*args, **kwargs):
        raise AssertionError("Preflight reached a device or persistence boundary")
    try:
        monkeypatch.setattr(fixture.port, "prepare", forbidden)
        monkeypatch.setattr(fixture.port, "prepare_processing", forbidden)
        monkeypatch.setattr(fixture.port, "check_ready", forbidden)
        monkeypatch.setattr(app.client.lifecycle.operations.space.repository, "put", forbidden)
        report, diagnostics = host.preflight.inspect(plan, init_state(plan), "preview")
        assert report["checked_effects"] == 2 and report["projected_path_complete"]
        assert len(diagnostics) == 2
        assert "PROCESSING_METHOD_PROFILE_REQUIRED" in diagnostics[0].message
        assert "PROCESSING_MODULE_UNAVAILABLE" in diagnostics[1].message
        assert all(d.node_id for d in diagnostics)
    finally:
        app.close()


def test_projection_does_not_change_language_state(tmp_path):
    fixture = SeparationContractFixture()
    plan, _, app = fixture.open(tmp_path)
    state = init_state(plan)
    state.artifacts["material_state"] = {"containers": {}}
    original = deepcopy(state)
    host = app.client.execution.host
    try:
        before = host.codec.dumps(state)
        report, diagnostics = host.preflight.inspect(plan, state, "projection")
        assert not diagnostics and report["status"] == "passed" and report["checked_effects"] == 2
        assert host.codec.dumps(state) == before and state == original
        assert not fixture.port.executions and not fixture.port.transfers
        result = app.execute(plan, state)
        assert result.ok
        assert len(fixture.port.processing) == 1 and len(fixture.port.transfers) == 1
        assert result.state.artifacts["material_state"] == run(plan, StubDriver(), deepcopy(original)).state.artifacts["material_state"]
        data, _ = host.restore(app.client.get_run(result.user_result["os"]["run_id"]).checkpoint)
        assert len(data["confirmed"]) == 2
        assert all("PREFLIGHT" not in record.resolution.code for record in data["confirmed"])
    finally:
        app.close()


def test_device_free_queue_uses_worker_preflight(tmp_path):
    fixture = SeparationContractFixture(profile=None)
    plan, _, app = fixture.open(tmp_path, BASE + "d << [s:10uL];" + SEP)
    try:
        checkpoint = HostedRuntimeInteractor().create(plan, init_state(plan), "queued")
        worker = app.client.execution.host
        data, _ = worker.restore(worker.advance(checkpoint))
        assert data["preflight"]["status"] == "rejected"
        assert data["pending"] is None and not data["confirmed"]
        assert not fixture.port.executions
    finally:
        app.close()


def test_partial_run_does_not_reproject(tmp_path, monkeypatch):
    fixture = SeparationContractFixture()
    plan, _, app = fixture.open(tmp_path)
    try:
        identity, pending = fixture.waiting(app, plan)
        def forbidden(*args, **kwargs):
            raise AssertionError("Partially executed run was projected again")
        monkeypatch.setattr(app.client.execution.host.preflight, "inspect", forbidden)
        result = app.client.run_until_settled(identity)
        assert result.status == "completed" and len(fixture.port.processing) == 1
    finally:
        app.close()


def test_group_projection_preserves_envelope(tmp_path):
    from .test_group_handoff import GroupFixture
    plan, _, app = GroupFixture().build(tmp_path)
    try:
        identity, pending = GroupFixture().pending(app, plan)
        assert isinstance(pending, PendingEffectGroup) and len(pending.members) == 8
        data, _ = app.client.execution.host.restore(app.client.get_run(identity).checkpoint)
        assert data["preflight"]["checked_effects"] == 8 and not data["confirmed"]
        assert not app.host.gateway.port.session.backend.receipts
        assert app.client.run_until_settled(identity).status == "completed"
    finally:
        app.close()


def test_no_action_needs_no_transfer_device(tmp_path):
    fixture = FakeSessionFactory()
    app = fixture.open(tmp_path)
    try:
        plan = TransferMatrixFixture().compile('let s=tube(capacity=200uL); s << [s:0uL];', tmp_path)
        preview = app.client.execution.host.preflight
        preview.snapshot = replace(preview.snapshot, supports_transfer=False)
        preview.space.positions = {}  # No physical binding is required for a logical-only effect.
        report, diagnostics = preview.inspect(plan, init_state(plan), "logical")
        assert report["status"] == "passed" and not diagnostics
        assert report["checked_effects"] == 1
    finally:
        app.close()


def test_explicit_transfer_capability_and_legacy_defer(tmp_path):
    app = FakeSessionFactory().open(tmp_path)
    try:
        request = ProgramFixture.request()
        preview = app.client.execution.host.preflight
        report, diagnostics = preview.inspect(request.plan, request.state, "legacy")
        assert not diagnostics and any("legacy" in item for item in report["deferred_checks"])
        preview.snapshot = replace(preview.snapshot, supports_transfer=False)
        report, diagnostics = preview.inspect(request.plan, request.state, "no-transfer")
        assert report["status"] == "rejected"
        assert any("TRANSFER_DEVICE_UNSUPPORTED" in d.message for d in diagnostics)
    finally:
        app.close()


def test_workspace_rejection_before_motion(tmp_path):
    app = FakeSessionFactory().open(tmp_path)
    try:
        app.client.execution.host.preflight.space.positions = {}
        request = ProgramFixture.request()
        result = app.execute(request.plan, request.state)
        assert not result.ok
        assert "WORKSPACE_BINDING_MISSING" in str(result.user_result["os"]["preflight"])
        assert not app.host.gateway.port.executions
    finally:
        app.close()


def test_preflight_architecture():
    root = Path(__file__).resolve().parents[1] / "src/culsma_os"
    tree = ast.parse((root / "program_manager/interactors/preflight.py").read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("repositories" in name or name.startswith(("pylabrobot", "culsma_opentrons")) for name in imports)
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls & {"prepare", "prepare_processing", "record_intent", "ingest", "reconcile", "acquire", "resume"}
    assert "OperationPreflightPort" in (root / "program_manager/models.py").read_text()


def test_late_model_error_rejects_without_committing_projection(tmp_path):
    app = FakeSessionFactory().open(tmp_path)
    try:
        plan = TransferMatrixFixture().compile(BASE + "d << [s:10uL]; d << [s:250uL];", tmp_path)
        result = app.execute(plan, init_state(plan))
        assert not result.ok
        report = result.user_result["os"]["preflight"]
        assert report["status"] == "rejected" and not report["projected_path_complete"]
        baseline = run(plan, StubDriver(), init_state(plan))
        expected = {d.code for d in baseline.diagnostics if d.severity == "error"}
        assert expected and expected <= {d["code"] for d in report["diagnostics"]}
        assert not app.host.gateway.port.executions
        assert not result.state.artifacts.get("material_state", {}).get("containers")
    finally:
        app.close()


def test_snapshot_capability_roundtrip_and_legacy_default():
    import json
    from dataclasses import asdict
    from culsma_os.device_manager.models import DeviceConfigurationSnapshot
    from culsma_os.device_manager.repository import SqliteDeviceRepository
    import sqlite3
    connection = sqlite3.connect(":memory:")
    try:
        repository = SqliteDeviceRepository(connection)
        for value in (True, False, None):
            snapshot = DeviceConfigurationSnapshot("fake", "simulation", "r1", (), supports_transfer=value)
            repository.put(snapshot)
            assert repository.get("fake") == snapshot
        legacy = asdict(snapshot)
        del legacy["supports_transfer"]
        assert repository.decode_snapshot(json.dumps(legacy)).supports_transfer is None
        with pytest.raises(ValueError, match="DEVICE_TRANSFER_CAPABILITY_INVALID"):
            replace(snapshot, supports_transfer=1)
    finally:
        connection.close()
