"""Whole-protocol acceptance using official simulated modules and durable OS state."""

from tests.support.paths import ROOT
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
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


EXAMPLE = ROOT / "examples/framework/combined-processing"


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
