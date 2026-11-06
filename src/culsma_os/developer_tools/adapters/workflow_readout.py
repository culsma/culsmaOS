"""Deterministic readout fixtures for the explicit OS workflow simulation mode."""
from culsma.runtime.material.args import arg_bool, arg_string


class WorkflowReadoutSimulator:
    provider = "internal_fluorescence_fixture_v1"

    def plan_step(self, step):
        quantity = step.args.get("quantity")
        if step.op != "img" or (arg_string(quantity) != "fluorescence" and quantity != {
                "kind": "ExternalEnum", "enum": "ReadoutQuantity", "member": "FLUORESCENCE"}):
            return None
        raw = step.args.get("save_raw")
        if raw is not None and arg_bool(raw) is not False:
            return None
        if step.args.get("program") is not None or step.args.get("schema_ref") is not None:
            return None
        return {"step_id": step.step_id, "operation": "img", "quantity": "fluorescence",
                "provider": self.provider, "synthetic": True,
                "result": {"signal": 100.0, "channel": "synthetic"}}
