from dataclasses import asdict, replace
from types import SimpleNamespace
import json
import sqlite3
import pytest
from culsma_os.device_manager.models import DeviceConfigurationSnapshot, ExecutionFeedbackCapabilities
from culsma_os.device_manager.repository import SqliteDeviceRepository
from culsma_os.driver_framework.models import DeviceReceipt, PlanContext, PreparedDevicePlan
from culsma_os.driver_framework.interactors import (
    FeedbackContractInteractor, DriverGatewayInteractor, NormalizedReceiptInteractor,
)
from tests.support.common import FakeSessionFactory, ProgramFixture


class TestFeedbackCapabilities:
    def fixture(self, units=("operation", "batch")):
        capability = ExecutionFeedbackCapabilities(units) if units is not None else None
        snapshot = DeviceConfigurationSnapshot("device", "simulation", "r1", (), feedback_capabilities=capability)
        device = SimpleNamespace(get=lambda _: snapshot, validate_ready=lambda _: None)
        context = PlanContext("run", "device", "simulation", "r1", "layout", "simulation", ())
        contract = FeedbackContractInteractor(device)
        intent = SimpleNamespace(step_id="step")
        description = contract.freeze({}, context, "operation", ("step",))
        plan = PreparedDevicePlan("effect", intent, context, None, description)
        receipt = DeviceReceipt("completed", "simulation", "step", "r1", {}, {"tips": 1})
        return device, contract, plan, receipt

    def test_snapshot_roundtrip_and_legacy(self):
        device, _, _, _ = self.fixture()
        with sqlite3.connect(":memory:") as connection:
            repository = SqliteDeviceRepository(connection)
            original = device.get("device")
            repository.put(original)
            assert repository.get("device") == original
            old = asdict(original)
            old.pop("feedback_capabilities")
            assert repository.decode_snapshot(json.dumps(old)).feedback_capabilities is None

    @pytest.mark.parametrize("units", [("channel",), ("member", "member"), ["operation"], ({},)])
    def test_invalid_declaration(self, units):
        with pytest.raises(ValueError, match="FEEDBACK_CAPABILITIES_INVALID"):
            ExecutionFeedbackCapabilities(units)

    def test_unsupported_unit_rejected_before_prepare(self):
        device, _, plan, _ = self.fixture()
        calls = []
        port = SimpleNamespace(prepare=lambda *args: calls.append(args))
        with pytest.raises(ValueError, match="FEEDBACK_UNIT_UNSUPPORTED"):
            DriverGatewayInteractor(port, device, None).prepare("effect", plan.intent, plan.context, (), completion_unit="member")
        assert calls == []

    @pytest.mark.parametrize("status", ["prepared", "not_submitted", "submitted", "accepted", "running", {}, ["completed"]])
    def test_nonterminal_status_never_completes(self, status):
        _, contract, plan, receipt = self.fixture()
        result = contract.normalize(plan, replace(receipt, payload={"execution_status": status}))
        assert result.outcome == "unknown"
        assert result.consumed_resources == {"tips": 1}
        assert result.payload["os_feedback"]["execution_status"] == status

    def test_outer_status_survives_mapper(self):
        _, contract, plan, _ = self.fixture()
        raw = {"outcome": "completed", "execution_status": "accepted", "mode": "simulation",
               "step_id": "step", "configuration_revision": "r1", "payload": {}, "consumed_resources": {}}
        receipt = NormalizedReceiptInteractor().map(plan, raw)
        assert contract.normalize(plan, receipt).outcome == "unknown"

    @pytest.mark.parametrize("claim", [
        {"completion_unit": "channel"}, {"completion_unit": "member"},
        {"covered_step_ids": []}, {"covered_step_ids": ["other"]},
        {"covered_step_ids": ["step", "extra"]},
    ])
    def test_invalid_receipt_scope_is_unknown(self, claim):
        _, contract, plan, receipt = self.fixture()
        result = contract.normalize(plan, replace(receipt, payload=claim))
        assert result.outcome == "unknown"
        assert result.consumed_resources == receipt.consumed_resources

    def test_exact_submission_completion(self):
        _, contract, plan, receipt = self.fixture()
        result = contract.normalize(plan, receipt)
        assert result.outcome == "completed"
        assert result.payload["os_feedback"] == {
            "execution_status": "completed", "completion_unit": "operation",
            "covered_step_ids": ["step"], "capabilities_declared": True, "diagnostic": None,
        }

    def test_legacy_only_confirms_submitted_unit(self):
        _, contract, plan, receipt = self.fixture(None)
        result = contract.normalize(plan, receipt)
        assert result.outcome == "completed"
        assert result.payload["os_feedback"]["capabilities_declared"] is False
        assert contract.normalize(plan, replace(receipt, payload={"completion_unit": "channel"})).outcome == "unknown"

    def test_capability_change_rejected_before_dispatch(self):
        device, _, plan, _ = self.fixture()
        snapshot = replace(device.get("device"), feedback_capabilities=ExecutionFeedbackCapabilities(("operation",)))
        device.get = lambda _: snapshot
        calls = []
        port = SimpleNamespace(execute=lambda *args: calls.append(args))
        gateway = DriverGatewayInteractor(port, device, NormalizedReceiptInteractor())
        permit = SimpleNamespace(effect_id=plan.effect_id, attempt_id="attempt", resources=())
        with pytest.raises(ValueError, match="FEEDBACK_CONTRACT_STALE"):
            gateway.execute(plan, permit, "attempt")
        assert calls == []

    @pytest.mark.parametrize("status", ["prepared", "accepted", "running"])
    def test_nonterminal_never_registers_material_or_releases_resources(self, tmp_path, status):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        try:
            port = factory.ports[0]
            original = port.execute
            def execute(plan, attempt_id):
                return {**original(plan, attempt_id), "execution_status": status}
            port.execute = execute
            app.client.start()
            run_id = app.client.submit_run(ProgramFixture.request())
            app.client.run_until_settled(run_id)
            evidence = app.client.lifecycle.evidence
            facts = [evidence.find_evidence(a.effect_id) for a in evidence.attempts_for_run(run_id)]
            assert facts and all(f.outcome == "unknown" for f in facts)
            assert app.client.get_run(run_id).status == "needs_reconciliation"
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.operations.material.get(run_id)[2] == 0
            assert len(port.executions) == 1
            app.client.run_until_settled(run_id)
            assert len(port.executions) == 1
        finally:
            app.close()

    def test_derived_members_retain_shared_feedback_scope(self, tmp_path):
        from importlib.util import find_spec
        from tests.acceptance.cross_platform_transfer import CrossPlatformTransferAcceptance
        if not all(find_spec(p) for p in ("culsma_opentrons", "culsma_pylabrobot", "pylabrobot")):
            pytest.skip("Requires both external simulator plugins")
        campaign = CrossPlatformTransferAcceptance()
        scenario = next(s for s in campaign.manifest["scenarios"] if s["name"] == "second-group-batch-fails")
        results = campaign.run_scenario(scenario, tmp_path / "paired")["backends"]
        ot, star = results["ot2"], results["star"]
        confirmed = [e for e in ot["evidence"] if e["outcome"] == "completed"]
        assert confirmed and all(e["payload"]["os_feedback"]["completion_unit"] == "member" for e in confirmed)
        assert all(e["payload"]["os_feedback"]["capabilities_declared"] for e in confirmed)
        shared = [e for e in star["evidence"] if "os_feedback" in e["payload"]]
        assert shared and all(e["payload"]["os_feedback"]["completion_unit"] == "batch" for e in shared)
        derived = [e for e in star["evidence"] if "shared_evidence_id" in e["payload"]]
        assert len(derived) == 8
        assert all(e["outcome"] == "unknown" and e["payload"]["shared_feedback"]["completion_unit"] == "batch" for e in derived)
        for result in results.values():
            for attempt in result["attempts"]:
                contract = attempt["context"]["description"].get("feedback_contract")
                if contract:
                    assert contract["capabilities"] is not None

    def test_conflicting_envelope_status_is_unknown(self):
        _, contract, plan, _ = self.fixture()
        raw = {"outcome": "completed", "execution_status": "completed", "mode": "simulation",
               "step_id": "step", "configuration_revision": "r1",
               "payload": {"execution_status": "accepted"}, "consumed_resources": {}}
        receipt = NormalizedReceiptInteractor().map(plan, raw)
        assert contract.normalize(plan, receipt).outcome == "unknown"

    def test_legacy_session_description_has_optional_declaration(self):
        pytest.importorskip("culsma_opentrons")
        from culsma_os.bootstrap import OpentronsSessionFactory
        from types import SimpleNamespace
        from unittest.mock import patch
        description = SimpleNamespace(device_id="legacy", mode="simulation", configuration_revision="r1",
            shared_resources=(), consumable_capacities={}, labware_geometries={}, transfer_channels=1,
            processing_capabilities={}, positions={}, capacities={})
        session = SimpleNamespace(describe_session=lambda: description, close=lambda: None)
        with patch("culsma_opentrons.plugin.SimulatorSessionFactory.create_from_file", return_value=session):
            _, snapshot, _, _, _ = OpentronsSessionFactory().build(SimpleNamespace(config_path=None, artifacts_dir=None))
        assert snapshot.feedback_capabilities is None

    def test_raw_nonterminal_outcome_is_preserved(self):
        _, contract, plan, _ = self.fixture()
        raw = {"outcome": "accepted", "mode": "simulation", "step_id": "step",
               "configuration_revision": "r1", "payload": {}, "consumed_resources": {}}
        receipt = contract.normalize(plan, NormalizedReceiptInteractor().map(plan, raw))
        assert receipt.outcome == "unknown"
        assert receipt.payload["os_feedback"]["execution_status"] == "accepted"

    def test_legacy_cannot_claim_channel_dispatch(self):
        device, _, plan, _ = self.fixture(None)
        calls = []
        port = SimpleNamespace(prepare=lambda *args: calls.append(args))
        with pytest.raises(ValueError, match="FEEDBACK_UNIT_UNSUPPORTED"):
            DriverGatewayInteractor(port, device, None).prepare("effect", plan.intent, plan.context, (), completion_unit="channel")
        assert calls == []

