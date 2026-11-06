"""Benchmark 02 software acceptance through explicit external simulation handoff."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from culsma.pipeline.plan_nodes import PlanStepTree
from culsma.runtime.material.args import arg_string
from culsma_os.bootstrap import OSApplicationFactory, OpentronsSessionFactory
from culsma_os.developer_tools.adapters.external_fixture import ExternalFixtureSimulator
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "selective-plating-handoff"


class SelectivePlatingFixture:
    def prepare(self, directory):
        compiler = CompilationInteractor()
        first = compiler.compile([EXAMPLE / "prepare.culs"])
        second = compiler.compile([EXAMPLE / "continue.culs"])
        for stage in (first, second):
            assert stage.semantic.ok and stage.typed.ok
        first_allocations = self.allocations(first.plan)
        second_allocations = self.allocations(second.plan)
        bindings = {
            step.step_id: {"labware": "tubes", "well": f"A{index + 1}"}
            for index, step in enumerate(first_allocations[:5])
        }
        bindings.update({
            step.step_id: {"labware": "plating", "well": f"A{index + 1}"}
            for index, step in enumerate(first_allocations[5:])
        })
        for index, step in enumerate(second_allocations):
            if index < 8:
                address = {"labware": "tubes", "well": f"{chr(65 + index // 6)}{index % 6 + 1}"}
            else:
                address = {"labware": "culture", "well": f"A{index - 7}"}
            assert bindings.setdefault(step.step_id, address) == address

        def configure(raw):
            raw["modules"] = {
                "temperature": {"model": "temperature module gen2", "slot": "3"},
                "shaker": {"model": "heaterShakerModuleV1", "slot": "10"},
            }
            raw["labware"].update(
                plating={"load_name": "opentrons_96_aluminumblock_nest_wellplate_100ul", "module": "temperature"},
                culture={"load_name": "nest_96_wellplate_200ul_flat",
                         "adapter": "opentrons_96_flat_bottom_adapter", "module": "shaker"},
            )
            raw["bindings"] = bindings

        context = TransferMatrixFixture().context(directory, first.plan, config_mutation=configure)
        return (replace(context, station_root=directory / "station"),
                RunRequest(first.plan, first.state), RunRequest(second.plan, second.state),
                [step.step_id for step in second_allocations[:8]])

    def allocations(self, plan):
        return [s for p in plan.plans for s in PlanStepTree.leaves(p.steps) if s.op == "AllocContainer"]

    def simulate(self, request):
        expected = request["expected_returns"]
        returned = {
            allocation: {"returned_sample_id": f"candidate-{index:02d}", **deepcopy(binding)}
            for index, (allocation, binding) in enumerate(expected.items(), 1)
        }
        provider = ExternalFixtureSimulator({
            "colony-imaging-and-selection": {
                "outcome": "completed",
                "sample_ids": request["sample_ids"],
                "observations": {
                    "plate_counts": {
                        sample_id: {"total": white + blue, "white": white, "blue": blue}
                        for sample_id, (white, blue) in zip(request["sample_ids"], ((8, 4), (1, 2), (0, 1), (0, 9), (0, 0)))
                    },
                    "selected_candidates": [row["returned_sample_id"] for row in returned.values()],
                },
                "returned_samples": returned,
            }
        })
        return provider.execute(request)


def test_benchmark02_handoff_survives_restart_and_executes_each_stage_once(tmp_path):
    fixture = SelectivePlatingFixture()
    context, phase_a, phase_b, allocations = fixture.prepare(tmp_path)
    factory = OSApplicationFactory()
    app = factory.build(context, external_simulation=True)
    try:
        app.client.start()
        source_run = app.client.submit_run(phase_a)
        source = app.client.run_until_settled(source_run)
        assert source.status == "completed"
        evidence = app.client.result(source_run).user_result["os"]["registered_material"]
        wells = {step.step_id: arg_string(step.args.get("carrier_position"))
                 for step in fixture.allocations(phase_a.plan)}
        plating = {wells[c["metadata"]["allocation_step_id"]]: (ref, c)
                   for ref, c in evidence["state"]["containers"].items() if c["metadata"]["kind"] == "well"}
        assert len(plating) == 5 and all(c["volume_uL"] == 100 for _, c in plating.values())
        sample_ids = tuple(plating[f"A{index}"][0] for index in range(1, 6))
        recombinant, = [ref for ref, c in evidence["state"]["containers"].items()
                        if "DH5A_RECOMBINANT_LIGATION" in c.get("component_quantities", {})
                        and c["metadata"]["kind"] == "well"]
        operation = "colony-imaging-and-selection"
        fields = ("plate_counts", "selected_candidates")
        bindings = dict.fromkeys(allocations, recombinant)
        handoff = app.client.external_simulation
        request = handoff.begin(source_run, phase_b, operation, sample_ids, bindings, fields)
        assert handoff.begin(source_run, phase_b, operation, sample_ids, bindings, fields) == request
        handoff_id = request["handoff_id"]
        assert handoff.get(handoff_id)["status"] == "awaiting_external_result"
        with pytest.raises(ValueError, match="EXTERNAL_RECEIPT_REQUIRED"):
            handoff.start_continuation(handoff_id)
    finally:
        app.close()

    restarted = factory.build(context, external_simulation=True)
    try:
        restarted.client.start()
        handoff = restarted.client.external_simulation
        assert handoff.get(handoff_id)["request"] == request
        assert restarted.client.get_run(source_run) == source
        receipt = fixture.simulate(request)
        wrong = deepcopy(receipt)
        wrong["returned_samples"][allocations[0]]["load"]["initial_volume_uL"] = 1
        with pytest.raises(ValueError, match="EXTERNAL_RETURN_SAMPLES_MISMATCH"):
            handoff.accept(handoff_id, wrong)
        wrong = deepcopy(receipt)
        wrong["returned_samples"][allocations[0]]["destination"]["well"] = "D6"
        with pytest.raises(ValueError, match="EXTERNAL_RETURN_SAMPLES_MISMATCH"):
            handoff.accept(handoff_id, wrong)
        with pytest.raises(ValueError, match="EXTERNAL_RECEIPT_MISMATCH"):
            handoff.accept(handoff_id, dict(receipt, mode="physical"))
        with pytest.raises(ValueError, match="EXTERNAL_RECEIPT_MISMATCH"):
            handoff.accept(handoff_id, dict(receipt, request_fingerprint="wrong"))
        with pytest.raises(ValueError, match="EXTERNAL_OBSERVATION_SAMPLES_MISMATCH"):
            handoff.accept(handoff_id, dict(receipt, sample_ids=sample_ids[:-1]))
        with pytest.raises(ValueError, match="EXTERNAL_RECEIPT_MISMATCH"):
            handoff.accept(handoff_id, dict(receipt, outcome="unknown"))
        assert handoff.get(handoff_id)["receipt"] is None
        assert handoff.accept(handoff_id, receipt) == handoff.accept(handoff_id, receipt)
        conflict = deepcopy(receipt)
        conflict["observations"]["plate_counts"][sample_ids[0]]["total"] += 1
        with pytest.raises(ValueError, match="EXTERNAL_RECEIPT_CONFLICT"):
            handoff.accept(handoff_id, conflict)
        continuation = handoff.start_continuation(handoff_id)
        assert handoff.start_continuation(handoff_id) == continuation
        assert restarted.client.get_run(continuation).simulation_only
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
    finally:
        restarted.close()

    resumed = factory.build(context, external_simulation=True)
    try:
        resumed.client.start()
        handoff = resumed.client.external_simulation
        assert handoff.start_continuation(handoff_id) == continuation
        completed = resumed.client.run_until_settled(continuation)
        assert completed.status == "completed"
        assert resumed.client.get_run(source_run) == source
        session = resumed.host.gateway.port.session
        assert len(session.backend.receipts) == 8
        shake, = session.agitation.receipts
        assert shake.payload["request"]["temperature_celsius"] == 37
        assert shake.payload["request"]["rate_rpm"] == 200
        assert shake.payload["request"]["duration_seconds"] == 57600
        assert len(shake.payload["request"]["targets"]) == 8
        assert not resumed.client.lifecycle.operations.resource.occupied()
        result = resumed.client.result(continuation).user_result["os"]["registered_material"]
        wells = [c for c in result["state"]["containers"].values() if c["metadata"]["kind"] == "well"]
        assert len(wells) == 8 and all(c["volume_uL"] == 100 for c in wells)
        status = handoff.get(handoff_id)
        assert status["receipt"] == receipt
        assert status["status"] == "completed" and status["continuation_run_id"] == continuation
        assert resumed.client.run_until_settled(continuation) == completed
        assert len(session.backend.receipts) == 8
    finally:
        resumed.close()


def test_external_fixture_provider_and_opt_in_are_simulation_only(tmp_path):
    class PhysicalModeFixture(OpentronsSessionFactory):
        def build(self, context):
            port, snapshot, positions, capacities, mapper = super().build(context)
            return port, replace(snapshot, mode="physical"), positions, capacities, mapper

    context, phase_a, _, _ = SelectivePlatingFixture().prepare(tmp_path)
    factory = OSApplicationFactory()
    ordinary = factory.build(context)
    try:
        assert ordinary.client.external_simulation is None
        run_id = "test-simulation-run"
        checkpoint = ordinary.client.tasks.prepare_checkpoint(phase_a, run_id)
        station = ordinary.client.lifecycle.device.configured_snapshot.execution_identity("local")
        continuation = ordinary.client.tasks.submit_simulation_continuation(run_id, checkpoint, station)
        ordinary.client.start()
        with pytest.raises(ValueError, match="EXTERNAL_SIMULATION_DISABLED"):
            ordinary.client.advance_run(continuation)
    finally:
        ordinary.close()
    physical_factory = OSApplicationFactory({"opentrons-simulator": PhysicalModeFixture()})
    with pytest.raises(ValueError, match="EXTERNAL_SIMULATION_REQUIRED"):
        physical_factory.build(context, external_simulation=True)
    physical = physical_factory.build(context)
    try:
        physical.client.start()
        with pytest.raises(ValueError, match="RUN_SIMULATION_MODE_REQUIRED"):
            physical.client.advance_run(continuation)
        assert not physical.host.gateway.port.session.backend.protocol.commands()
    finally:
        physical.close()
    changed = factory.build(replace(context, station_id="different"), external_simulation=True)
    try:
        changed.client.start()
        with pytest.raises(ValueError, match="EXTERNAL_STATION_CHANGED"):
            changed.client.advance_run(continuation)
        assert not changed.host.gateway.port.session.backend.protocol.commands()
    finally:
        changed.close()
    with pytest.raises(ValueError, match="EXTERNAL_SIMULATION_REQUIRED"):
        ExternalFixtureSimulator({}).execute({"mode": "physical"})
