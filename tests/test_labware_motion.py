"""Real official Flex simulator integration; motion stays outside language semantics."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import ast
import json
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma.runtime.material.args import arg_string
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from .test_transfer_matrix import TransferMatrixFixture, BUFFER

SOURCE = f'''let p=plate(label="Assay",format="96well",capacity=200uL);
let wells=p[A1:A2];
let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:100uL]);
wells[0] << [stock:50uL];
stock << [wells[0]:20uL];
return wells[0];'''


class MotionFixture:
    def build(self, directory, change=None, source=SOURCE):
        plan = TransferMatrixFixture().compile(source, directory)
        mutations = [s for p in plan.plans for s in p.steps if s.op == "Mutation"]
        raw = {"robot_type":"Flex", "api_level":"2.20", "pipette":"flex_1channel_1000", "mount":"left",
            "tiprack":{"load_name":"opentrons_flex_96_tiprack_1000ul","slot":"D3"},
            "labware":{"assay":{"load_name":"nest_96_wellplate_200ul_flat","slot":"D1"},
                       "stock":{"load_name":"opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap","slot":"C1"}},
            "bindings":{}, "labware_moves":{
                mutations[0].step_id:[{"labware":"assay","destination":"D2"}],
                mutations[1].step_id:[{"labware":"assay","destination":"D1"}]}}
        for s in (s for p in plan.plans for s in p.steps if s.op == "AllocContainer"):
            raw["bindings"][s.step_id] = ({"labware":"assay", "well":arg_string(s.args["carrier_position"])}
                if "carrier_position" in s.args else {"labware":"stock", "well":"A1"})
        if change:
            change(raw)
        path = directory / "deck.json"
        path.write_text(json.dumps(raw))
        from culsma_os.program_manager.models import HostBuildContext
        context = HostBuildContext(directory/"os.sqlite3", "opentrons-simulator", path, directory/"artifacts")
        return plan, context, OSApplicationFactory().build(context)

    def waiting(self, app, plan):
        app.client.start()
        identity = app.client.submit_run(RunRequest(plan, init_state(plan)))
        app.client.lifecycle.runs.advance_ready(identity)
        return identity, app.client.execution.pending(identity)


@pytest.mark.parametrize("pipette", ["flex_1channel_1000", "flex_1channel_50"])
def test_move_transfer_return_matches_language(tmp_path, monkeypatch, pipette):
    def change(raw):
        raw["pipette"] = pipette
        raw["tiprack"]["load_name"] = "opentrons_flex_96_tiprack_50ul" if pipette.endswith("50") else "opentrons_flex_96_tiprack_1000ul"
    plan, context, app = MotionFixture().build(tmp_path, change)
    session = app.host.gateway.port.session
    locations = []
    original = session.backend.pipette.aspirate
    def observe(*args, **kwargs):
        locations.append(str(session.backend.labware["assay"].parent))
        return original(*args, **kwargs)
    monkeypatch.setattr(session.backend.pipette, "aspirate", observe)
    try:
        result = app.execute(plan, init_state(plan))
        assert result.ok, [d.to_dict() for d in result.diagnostics]
        baseline = run(plan, StubDriver(), init_state(plan))
        assert result.state.artifacts["material_state"] == baseline.state.artifacts["material_state"]
        assert result.state.artifacts["protocol_outputs"] == baseline.state.artifacts["protocol_outputs"]
        assert locations == ["D2", "D1"]
        assert len(session.motion.receipts) == 2 and len(session.backend.receipts) == 2
        assert [c for c in session.backend.protocol.commands() if "with gripper" in c] == [
            "Moving nest_96_wellplate_200ul_flat to slot D2 with gripper",
            "Moving nest_96_wellplate_200ul_flat to slot D1 with gripper"]
        motions = app.client.lifecycle.operations.motions
        revision, positions = motions.motion.positions()
        assert revision == 2 and positions["assay"] == "D1"
        identity = result.user_result["os"]["run_id"]
        assert app.host.material.get(identity)[2] == 2
        attempts = app.client.lifecycle.evidence.attempts_for_run(identity)
        assert len(attempts) == 4
        assert all(motions.registered(a, app.client.lifecycle.evidence.find_evidence(a.effect_id))
            for a in attempts if motions.motion.is_move_attempt(a))
        assert not app.client.lifecycle.operations.resource.occupied()
    finally:
        app.close()


@pytest.mark.parametrize("problem", ["occupied", "unknown-step", "untyped-carrier"])
def test_route_rejections_have_no_actions(tmp_path, problem):
    def change(raw):
        first = next(iter(raw["labware_moves"]))
        if problem == "occupied": raw["labware_moves"][first][0]["destination"] = "D3"
        if problem == "unknown-step": raw["labware_moves"]["missing"] = raw["labware_moves"].pop(first)
        if problem == "untyped-carrier":
            raw["labware"]["stock"] = {"load_name":"nest_96_wellplate_200ul_flat", "slot":"C1"}
            raw["labware_moves"][first][0]["labware"] = "stock"
    plan, _, app = MotionFixture().build(tmp_path, change, source=SOURCE.replace("capacity=2000uL", "capacity=200uL") if problem == "untyped-carrier" else SOURCE)
    try:
        result = app.execute(plan, init_state(plan))
        assert not result.ok and "MOTION_" in str(result.diagnostics)
        assert result.user_result["os"]["preflight"]["status"] == "rejected"
        assert not app.host.gateway.port.session.backend.protocol.commands()
        assert not app.client.lifecycle.evidence.attempts_for_run(result.user_result["os"]["run_id"])
    finally:
        app.close()


def test_unknown_move_blocks_transfer_and_restart(tmp_path, monkeypatch):
    plan, context, app = MotionFixture().build(tmp_path)
    identity, pending = MotionFixture().waiting(app, plan)
    session = app.host.gateway.port.session
    original = session.backend.protocol.move_labware
    def uncertain(*args, **kwargs):
        original(*args, **kwargs)
        raise TimeoutError("lost completion after virtual move")
    monkeypatch.setattr(session.backend.protocol, "move_labware", uncertain)
    try:
        result = app.client.run_until_settled(identity)
        assert result.status == "needs_reconciliation"
        assert not session.backend.receipts
        assert app.client.lifecycle.operations.resource.occupied()
        assert app.client.lifecycle.operations.motions.motion.positions()[0] == 0
        assert app.client.lifecycle.operations.resource.reservations.get(identity).status == "active"
    finally:
        app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity)
        restarted.client.start()
        assert restarted.client.run_until_settled(identity).status == "needs_reconciliation"
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
        assert restarted.client.lifecycle.operations.resource.occupied()
    finally:
        restarted.close()


@pytest.mark.parametrize("point", ["registration", "after-registration"])
def test_saved_evidence_repairs_position_without_replay(tmp_path, monkeypatch, point):
    plan, context, app = MotionFixture().build(tmp_path)
    identity, pending = MotionFixture().waiting(app, plan)
    motion = app.client.lifecycle.operations.motions.motion
    original = motion.register
    def crash(*args, **kwargs):
        if point == "after-registration": original(*args, **kwargs)
        raise KeyboardInterrupt("after durable motion completion")
    monkeypatch.setattr(motion, "register", crash)
    try:
        with pytest.raises(KeyboardInterrupt): app.client.lifecycle.operations.dispatch_ready(identity)
        assert len(app.host.gateway.port.session.motion.receipts) == 1
        assert not app.host.gateway.port.session.backend.receipts
        assert app.client.lifecycle.evidence.find_evidence(pending.effect_id + "/motion/0").outcome == "completed"
    finally:
        app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        assert str(restarted.host.gateway.port.session.backend.labware["assay"].parent) == "D2"
        restarted.client.take_over_run(identity)
        restarted.client.start()
        record = restarted.client.run_until_settled(identity)
        assert record.status == "completed", record
        session = restarted.host.gateway.port.session
        assert len(session.motion.receipts) == 1  # Only the new, later return move.
        assert session.motion.receipts[0].payload["request"]["source"] == "D2"
        assert len(session.backend.receipts) == 2
        assert restarted.host.result(identity).state.artifacts["material_state"] == run(plan, StubDriver()).state.artifacts["material_state"]
    finally:
        restarted.close()


def test_position_registration_does_not_change_material(tmp_path):
    plan, _, app = MotionFixture().build(tmp_path)
    try:
        identity, pending = MotionFixture().waiting(app, plan)
        before = deepcopy(pending.before_material_state)
        motions = app.client.lifecycle.operations.motions
        assert motions.before_effect(identity, pending)
        assert app.client.execution.pending(identity).before_material_state == before
        with pytest.raises(KeyError): app.host.material.get(identity)
        assert motions.motion.positions()[0] == 1
        app.client.run_until_settled(identity)
    finally:
        app.close()


def test_motion_architecture():
    root = Path(__file__).resolve().parents[1]/"src/culsma_os"
    for filename in ("workspace_manager/interactors.py", "scheduler/interactors.py"):
        imports = [n.module or "" for n in ast.walk(ast.parse((root/filename).read_text())) if isinstance(n, ast.ImportFrom)]
        assert not any(n.startswith(("culsma_opentrons", "opentrons")) for n in imports)
    assert "class CarrierRef" in (root/"workspace_manager/models.py").read_text()
    assert "material.reconcile" not in (root/"scheduler/interactors.py").read_text().split("class MotionSchedulerInteractor:")[1]


@pytest.mark.parametrize("problem", ["missing-receipt", "malformed-completion"])
def test_unconfirmed_motion_never_commits_position(tmp_path, monkeypatch, problem):
    plan, context, app = MotionFixture().build(tmp_path)
    identity, pending = MotionFixture().waiting(app, plan)
    operations = app.client.lifecycle.operations
    original = app.host.gateway.execute
    def altered(plan, permit, attempt_id):
        receipt = original(plan, permit, attempt_id)
        if plan.description.get("operation_kind") == "labware_move":
            if problem == "missing-receipt": raise TimeoutError("receipt lost")
            payload = deepcopy(receipt.payload)
            payload["request"]["destination"] = "C2"
            return replace(receipt, payload=payload)
        return receipt
    monkeypatch.setattr(app.host.gateway, "execute", altered)
    try:
        assert app.client.run_until_settled(identity).status == "needs_reconciliation"
        assert operations.motions.motion.positions()[0] == 0
        occupied = operations.resource.occupied()
        assert any("slot:D1" in value for value in occupied)
        assert any("slot:D2" in value for value in occupied)
        assert not app.host.gateway.port.session.backend.receipts
    finally:
        app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity)
        restarted.client.start()
        assert restarted.client.run_until_settled(identity).status == "needs_reconciliation"
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
    finally:
        restarted.close()


def test_cancel_repairs_completed_motion_without_pipetting(tmp_path, monkeypatch):
    plan, context, app = MotionFixture().build(tmp_path)
    identity, pending = MotionFixture().waiting(app, plan)
    def crash(*args, **kwargs): raise KeyboardInterrupt("before position registration")
    monkeypatch.setattr(app.client.lifecycle.operations.motions.motion, "register", crash)
    try:
        with pytest.raises(KeyboardInterrupt): app.client.lifecycle.operations.dispatch_ready(identity)
        app.client.lifecycle.tasks.request_cancel(identity)
    finally:
        app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity)
        assert restarted.client.get_run(identity).status == "cancelled"
        assert restarted.client.lifecycle.operations.motions.motion.positions()[1]["assay"] == "D2"
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
        assert not restarted.client.lifecycle.operations.resource.occupied()
    finally:
        restarted.close()


def test_repeated_runs_keep_position_history_and_do_not_double_register(tmp_path):
    plan, context, app = MotionFixture().build(tmp_path)
    try:
        for expected in (2, 4):
            result = app.execute(plan, init_state(plan))
            assert result.ok
            motion = app.client.lifecycle.operations.motions.motion
            assert motion.positions()[0] == expected
            identity = result.user_result["os"]["run_id"]
            for attempt in app.client.lifecycle.evidence.attempts_for_run(identity):
                if motion.is_move_attempt(attempt):
                    motion.register(attempt, app.client.lifecycle.evidence.find_evidence(attempt.effect_id))
            assert motion.positions()[0] == expected
        assert len(app.host.gateway.port.session.motion.receipts) == 4
        assert len(app.host.gateway.port.session.backend.receipts) == 4
    finally:
        app.close()
