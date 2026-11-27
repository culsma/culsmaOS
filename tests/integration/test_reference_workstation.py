"""Run the documented program through the actual Opentrons CLI and device session."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


@pytest.fixture
def example():
    pytest.importorskip("culsma_opentrons")
    return Path(__file__).resolve().parents[2] / "examples/reference-centrifuge"


def evidence(directory):
    with sqlite3.connect(directory / "culsma-os.sqlite3") as db:
        return [json.loads(record) for record, in db.execute("SELECT record FROM os_evidence ORDER BY rowid")]


def kinds(records):
    return [record["payload"].get("operation_kind", "transfer") for record in records]


@pytest.mark.parametrize("cooled", [True, False])
def test_reference_centrifuge_from_original_cli(example, tmp_path, cooled):
    config = example / ("workstation.json" if cooled else "workstation-uncooled.json")
    process = subprocess.run(
        [str(Path(sys.executable).with_name("culsma")), "run", str(example / "protocol.culs"),
         "--driver", "os-opentrons-simulator", "--driver-config", str(config),
         "--artifacts-dir", str(tmp_path), "--json"],
        capture_output=True, text=True, timeout=30, cwd=tmp_path,
    )
    report = json.loads(process.stdout)
    records = evidence(tmp_path)
    if not cooled:
        assert process.returncode != 0
        assert report["report"]["os"]["preflight"]["status"] == "rejected"
        assert any("thermal=4 C" in alert for alert in report["report"]["alerts"])
        assert not records
        return
    assert process.returncode == 0, process.stdout + process.stderr
    assert report["ok"]
    assert kinds(records) == ["transfer", "labware_move", "centrifuge", "labware_move", "transfer"]
    assert all(row["mode"] == "simulation" and row["outcome"] == "completed" for row in records)
    fill, load, spin, unload, collect = (row["payload"] for row in records)
    assert load["request"]["destination"] == "module:rotor"
    assert unload["request"]["destination"] == "D1"
    assert [a["action"] for a in load["reference_dock_actions"]] == ["open_lid", "load", "close_lid"]
    assert [a["action"] for a in unload["reference_dock_actions"]] == ["open_lid", "unload", "close_lid"]
    assert load["sdk_movement"]["backend"] == unload["sdk_movement"]["backend"] == "official-opentrons"
    assert any("B1" in command for command in load["sdk_movement"]["commands"])
    assert spin["evidence_scope"] == "reference_centrifuge_model"
    assert spin["cycle_settings"] == {
        "drive_unit": "g", "drive_value": 300, "duration_seconds": 300,
        "temperature_celsius": 4, "labware": "assay",
    }
    assert spin["virtual_elapsed_seconds"] == 300
    assert not spin["sample_temperature_measured"]
    assert collect["selection"]["producer_step_id"] == spin["request"]["step_id"]
    sample_id = spin["request"]["targets"][0]["container_id"]
    assert fill["transfers"][0]["target"]["id"] == collect["transfers"][0]["source"]["id"] == sample_id
    assert collect["transfers"][0]["volume_uL"] == 40
    assert sorted(c["volume_uL"] for c in
                  json.loads((tmp_path / "run.json").read_text())["state"]["artifacts"]["material_state"]["containers"].values()) == [0, 10, 40]


@pytest.mark.parametrize("stage", ["load", "spin"])
def test_uncertain_reference_action_blocks_later_work_and_survives_restart(example, tmp_path, monkeypatch, stage):
    from culsma_opentrons.models import DriverValidationError

    plan = TransferMatrixFixture().compile((example / "protocol.culs").read_text(), tmp_path)
    context = HostBuildContext(
        tmp_path / "culsma-os.sqlite3", "opentrons-simulator",
        example / "workstation.json", tmp_path / "artifacts",
    )
    app = OSApplicationFactory().build(context)
    try:
        session = app.host.gateway.port.session
        rotor = session.centrifuges["rotor"].backend

        def lose_completion(*args, **kwargs):
            raise TimeoutError("injected loss of reference device completion")

        monkeypatch.setattr(
            rotor, "load" if stage == "load" else "_complete_cycle", lose_completion,
        )
        result = app.execute(plan, init_state(plan))
        assert not result.ok
        records = evidence(tmp_path)
        assert kinds(records) == (["transfer", "labware_move", "centrifuge"]
                                   if stage == "spin" else ["transfer", "labware_move"])
        assert records[-1]["outcome"] == "unknown"
        assert len(session.backend.receipts) == 1
        assert session.motion.repository.load()["uncertain"]
        if stage == "load":
            assert records[-1]["payload"]["phases"]["move"] == "returned"
            assert session.motion.positions()["assay"] == "D1"
            assert session.motion.current_location("assay") == "module:rotor"
        else:
            assert rotor.read_state().uncertain
            assert session.motion.positions()["assay"] == "module:rotor"
    finally:
        app.close()

    reopened = OSApplicationFactory().build(context)
    try:
        session = reopened.host.gateway.port.session
        with pytest.raises(DriverValidationError, match="not confirmed"):
            session.check_ready()
    finally:
        reopened.close()


@pytest.mark.parametrize("stage", ["load", "spin"])
@pytest.mark.parametrize("as_json", [False, True])
def test_cli_reports_reference_fault_at_program_step(example, tmp_path, monkeypatch, capsys, stage, as_json):
    from culsma.cli import main
    from culsma_opentrons.centrifuge import CentrifugeSimulationBackend, RotorPosition

    original_load = CentrifugeSimulationBackend.load

    def fail_sample_load(self, position, load):
        if position == RotorPosition.SAMPLE:
            raise TimeoutError("simulated completion confirmation lost")
        return original_load(self, position, load)

    def fail_cycle_completion(self):
        raise TimeoutError("simulated completion confirmation lost")

    if stage == "load":
        monkeypatch.setattr(CentrifugeSimulationBackend, "load", fail_sample_load)
    else:
        monkeypatch.setattr(CentrifugeSimulationBackend, "_complete_cycle", fail_cycle_completion)
    monkeypatch.setenv("CULSMA_OS_STATION_ROOT", str(tmp_path / "stations"))
    argv = ["culsma", "run", str(example / "protocol.culs"), "--driver", "os-opentrons-simulator",
            "--driver-config", str(example / "workstation.json"), "--artifacts-dir", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv + (["--json"] if as_json else []))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    bundle = json.loads((tmp_path / "run.json").read_text())
    diagnostic, = [d for d in bundle["diagnostics"] if d["code"] == "OS_DEVICE_OPERATION_UNCONFIRMED"]
    source_line = (example / "protocol.culs").read_text().splitlines()[diagnostic["span"]["line"] - 1]
    assert source_line.strip().startswith("sep(")
    report = bundle["user_result"]
    fault, = report["os"]["faults"]
    records = evidence(tmp_path)
    assert fault == records[-1]["payload"]["faults"][0]
    assert report["os"]["status"] == "needs_reconciliation"
    assert fault["context"]["module"] == "rotor"
    assert fault["operation_id"] == diagnostic["node_id"] + ("/motion/0" if stage == "load" else "")
    assert records[-1]["outcome"] == "unknown"
    assert kinds(records) == ["transfer", "labware_move"] + (["centrifuge"] if stage == "spin" else [])
    if as_json:
        payload = json.loads(output)
        assert payload["ok"] is False
        assert payload["report"]["diagnostics"] == [diagnostic]
        assert payload["report"]["os"]["faults"] == [fault]
    else:
        assert output.count(diagnostic["message"]) == 1
        assert f"line {diagnostic['span']['line']}" in output
        assert output.index(diagnostic["message"]) < output.index("partial results:")
