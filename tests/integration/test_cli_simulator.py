from tests.support.paths import ROOT
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.driver_framework.interactors import DriverLoaderInteractor
from culsma.frontend.resolver import resolve_files
from culsma.pipeline.compile import compile_ast
from culsma.pipeline.plan import lower_ir_to_plan
from culsma.pipeline.typecheck import typecheck
from culsma.pipeline.validate import validate
from culsma_opentrons.support import validate_plan_support
from tests.support.integration.cli_simulator import culsma_opentrons, ROOT, compile_example


def test_standard_cli_installed_driver(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "culsma_os.cli",
            "driver-run",
            str(ROOT / "examples/transfer.culs"),
            "--driver",
            "opentrons-simulator",
            "--driver-config",
            str(ROOT / "examples/deck.json"),
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    artifact = json.loads((tmp_path / "artifacts/run.json").read_text())
    assert artifact["ok"]
    receipts = [
        event for event in artifact["events"] if "DRV_OT_SIMULATED" in json.dumps(event)
    ]
    assert len(receipts) == 2
    assert "Aspirating 50.0 uL from A1" in json.dumps(receipts)


def test_compile_failure_precedes_driver_loading(tmp_path, monkeypatch):
    source = tmp_path / "bad.culs"
    source.write_text("let destination = tube(); destination << [missing:50uL];")

    def must_not_start(*args):
        raise AssertionError("Driver loaded for invalid source")

    monkeypatch.setattr(
        "culsma_os.driver_framework.interactors.DriverLoaderInteractor.load_factory",
        must_not_start,
    )
    bundle = (
        OSApplicationFactory()
        .build_program_runner()
        .execute_pipeline(
            [source], driver_name="opentrons-simulator", execution_mode="driver"
        )
    )
    assert not bundle["run"]["ok"]


def test_standard_cli_failure_receipt(tmp_path):
    import subprocess
    import sys

    artifacts = tmp_path / "failure-artifacts"
    script = """
import os, sys
from pathlib import Path
os.environ['OT_API_CONFIG_DIR'] = str((Path(sys.argv[1]) / 'driver/vendor-config').resolve())
from culsma_opentrons.backend import OfficialSimulatorBackend
original_init = OfficialSimulatorBackend.__init__
def initialize(self, config, restored_locations=None):
    original_init(self, config, restored_locations)
    def fail(*args):
        raise RuntimeError('injected simulator failure')
    self.pipette.aspirate = fail
OfficialSimulatorBackend.__init__ = initialize
from culsma_os.cli import CulsmaOSCLI
sys.argv = ['culsma-os', 'driver-run', sys.argv[2], '--driver', 'opentrons-simulator', '--driver-config', sys.argv[3], '--artifacts-dir', sys.argv[1]]
CulsmaOSCLI.main()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(artifacts),
            str(ROOT / "examples/transfer.culs"),
            str(ROOT / "examples/deck.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr + result.stdout
    run_artifact = json.loads((artifacts / "run.json").read_text())
    assert not run_artifact["ok"]
    payload = json.dumps(run_artifact["events"])
    assert "injected simulator failure" in payload
    assert '"retry_safe": false' in payload
    assert "Picking up tip" in payload
    containers = run_artifact["state"]["artifacts"]["material_state"]["containers"]
    assert sorted(c["volume_uL"] for c in containers.values()) == [0, 200]


@pytest.mark.parametrize(
    "name,strokes",
    [
        ("multi-source", 2),
        ("low-volume-recipe", 4),
        ("serial-dilution", 2),
        ("split-transfer", 3),
    ],
)
def test_benchmark_examples(name, strokes, tmp_path):
    artifact_dir = tmp_path / name
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "culsma_os.cli",
            "driver-run",
            str(ROOT / "examples" / name / "protocol.culs"),
            "--driver",
            "opentrons-simulator",
            "--driver-config",
            str(ROOT / "examples" / name / "deck.json"),
            "--artifacts-dir",
            str(artifact_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    artifact = json.loads((artifact_dir / "run.json").read_text())
    expected = json.loads((ROOT / "examples" / name / "expected.json").read_text())
    containers = artifact["state"]["artifacts"]["material_state"]["containers"]
    assert sorted(c["volume_uL"] for c in containers.values()) == pytest.approx(
        sorted(expected["volumes_uL"])
    )
    receipts = [
        event["payload"]["driver_payload"]
        for event in artifact["events"]
        if event["payload"].get("driver_code") == "DRV_OT_SIMULATED"
    ]
    assert sum(len(r["transfers"]) for r in receipts) == strokes
    assert sum(len(r["action_results"]) for r in receipts) == 4 * strokes
    assert all(
        action["status"] == "returned"
        for r in receipts
        for action in r["action_results"]
    )
    action_ids = [a["action_id"] for r in receipts for a in r["action_results"]]
    assert len(action_ids) == len(set(action_ids))
    assert all(
        r["span"] and r["schema"] == "opentrons_transfer_receipt_v1" for r in receipts
    )
    for receipt in receipts:
        canonical = json.dumps(
            receipt["effective_config"], sort_keys=True, separators=(",", ":")
        )
        assert (
            receipt["config_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
        )
    if name == "low-volume-recipe":
        assert [t["volume_uL"] for t in receipts[0]["transfers"]] == [2, 2, 2, 4]
        assert all(
            "at 3.0" in c for c in receipts[0]["commands"] if c.startswith("Aspirating")
        )
        assert all(
            "at 4.0" in c for c in receipts[0]["commands"] if c.startswith("Dispensing")
        )
    if name == "serial-dilution":
        second = next(
            c
            for c in containers.values()
            if c["volume_uL"] == pytest.approx(300) and len(c["components"]) == 2
        )
        assert second["components"]["STOCK"] == pytest.approx(100 / 3)
        assert second["components"]["DILUENT"] == pytest.approx(800 / 3)
    if name == "multi-source":
        mixture = next(
            c
            for c in containers.values()
            if "FIRST" in c["components"] and "SECOND" in c["components"]
        )
        assert mixture["components"] == {"FIRST": 50, "SECOND": 100}


def test_separation_preflight(tmp_path):
    plan = compile_example("unsupported-separation")
    with pytest.raises(ValueError, match="separation requires"):
        validate_plan_support(plan)
    artifact_dir = tmp_path / "unsupported"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "culsma_os.cli",
            "driver-run",
            str(ROOT / "examples/unsupported-separation/protocol.culs"),
            "--driver",
            "opentrons-simulator",
            "--driver-config",
            str(ROOT / "examples/unsupported-separation/deck.json"),
            "--artifacts-dir",
            str(artifact_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert (
        "DRV_OT_SEPARATION_UNSUPPORTED" in result.stderr
        or "separation requires" in result.stderr
    )
    assert not (artifact_dir / "driver/vendor-config").exists()


def test_external_os_cli_main_chain(tmp_path):
    artifact_dir = tmp_path / "os-cli"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "culsma_os.cli",
            "run",
            str(ROOT / "examples/transfer.culs"),
            "--driver",
            "opentrons-simulator",
            "--driver-config",
            str(ROOT / "examples/deck.json"),
            "--artifacts-dir",
            str(artifact_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    artifact = json.loads((artifact_dir / "run.json").read_text())
    assert artifact["ok"] and artifact["user_result"]["os"]["status"] == "completed"
    import sqlite3

    with sqlite3.connect(artifact_dir / "culsma-os.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM os_evidence").fetchone()[0] == 2

