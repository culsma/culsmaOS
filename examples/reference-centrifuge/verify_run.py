"""Check and export a recorded reference centrifuge run."""

import argparse
import json
from pathlib import Path
import sqlite3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(directory, expect):
    result = json.loads((directory / "run.json").read_text())
    with sqlite3.connect(f"{(directory / 'culsma-os.sqlite3').resolve().as_uri()}?mode=ro", uri=True) as db:
        effects = [json.loads(record) for record, in db.execute("SELECT record FROM os_evidence ORDER BY rowid")]
    if expect == "temperature-rejected":
        require(not result["ok"] and not effects, "Expected rejection before the first device action")
        require(any(
            "PROCESSING_ENVIRONMENT_CONDITION_UNSUPPORTED" in item["message"]
            and "thermal=4 C" in item["message"] for item in result["diagnostics"]
        ), "Expected an explicit rejection of the 4 °C request")
        return {"outcome": expect, "device_effects": [], "diagnostics": result["diagnostics"]}

    require(result["ok"], "Expected a completed run")
    kinds = [effect["payload"].get("operation_kind", "transfer") for effect in effects]
    require(kinds == ["transfer", "labware_move", "centrifuge", "labware_move", "transfer"],
            f"Unexpected operation order: {kinds}")
    require(all(effect["mode"] == "simulation" and effect["outcome"] == "completed" for effect in effects),
            "Expected five confirmed simulated effects")
    fill, load, spin, unload, collect = (effect["payload"] for effect in effects)
    require(load["request"]["destination"] == "module:rotor" and unload["request"]["destination"] == "D1",
            "Expected a round trip to the reference rotor")
    require(all(move["sdk_movement"]["backend"] == "official-opentrons" and move["sdk_movement"]["commands"]
                for move in (load, unload)), "Expected SDK movement evidence")
    require(spin["cycle_settings"] == {
        "drive_value": 300, "drive_unit": "g", "duration_seconds": 300,
        "temperature_celsius": 4, "labware": "assay",
    } and spin["virtual_elapsed_seconds"] == 300 and spin["rotor_stopped"], "Incorrect reference cycle")
    require(spin["evidence_scope"] == "reference_centrifuge_model" and not spin["sample_temperature_measured"],
            "Expected reference model evidence")
    require(collect["selection"]["producer_step_id"] == spin["request"]["step_id"],
            "Supernatant transfer is not linked to the centrifuge cycle")
    sample_id = spin["request"]["targets"][0]["container_id"]
    require(fill["transfers"][0]["target"]["id"] == collect["transfers"][0]["source"]["id"] == sample_id,
            "The sample identity changed")
    require(collect["transfers"][0]["volume_uL"] == 40, "Expected a 40 µL transfer")
    return {"outcome": expect, "device_effects": effects}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--expect", choices=("completed", "temperature-rejected"), default="completed")
    args = parser.parse_args()
    try:
        report = verify(args.artifacts, args.expect)
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
