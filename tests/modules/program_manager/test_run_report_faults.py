from types import SimpleNamespace

from culsma.common.source import Span
from culsma.pipeline.plan_nodes import PlanProgram, PlanStep, ProtocolPlan
from culsma_os.event_journal.models import AttemptRecord, ExecutionEvidence
from culsma_os.program_manager.interactors.host import RunReportInteractor


def test_receipt_faults_requires_matching_attempt_and_noncompleted_receipt():
    fault = {"code": "DEVICE_ERROR"}
    attempts = [
        AttemptRecord(identity, "run", identity, "simulation", {})
        for identity in ("fault", "missing", "wrong-attempt", "wrong-run", "completed")
    ]
    receipts = {
        "fault": ExecutionEvidence("e1", "run", "fault", "fault", "simulation", "unknown", {"faults": [fault]}, {}),
        "wrong-attempt": ExecutionEvidence("e2", "run", "wrong-attempt", "different", "simulation", "unknown", {"faults": [fault]}, {}),
        "wrong-run": ExecutionEvidence("e3", "other", "wrong-run", "wrong-run", "simulation", "unknown", {"faults": [fault]}, {}),
        "completed": ExecutionEvidence("e4", "run", "completed", "completed", "simulation", "completed", {"faults": [fault]}, {}),
    }
    evidence = SimpleNamespace(attempts_for_run=lambda _: attempts, find_evidence=receipts.get)
    report = RunReportInteractor(None, None, None, evidence=evidence)
    assert report.receipt_faults("run") == [(attempts[0], fault)]


def test_completion_diagnostic_uses_motion_parent_and_tolerates_optional_native_details():
    span = Span(13, 3, 100, 150)
    step = PlanStep("entry.s0", "sep", span=span)
    plan = PlanProgram(plans=[ProtocolPlan("entry", "entry", steps=[step])])
    attempt = AttemptRecord("a", "r", "e", "simulation", {"step_id": "entry.s0/motion/0"})
    fault = {"reason": "culsma.operation.completion_unconfirmed",
             "context": {"module": "rotor"}, "native_details": {}}
    report = RunReportInteractor(None, None, None)
    diagnostic, = report.fault_diagnostics(plan, [(attempt, fault), (attempt, fault)])
    assert diagnostic.node_id == "entry.s0"
    assert diagnostic.span == span
    assert diagnostic.message == "Completion is not confirmed for device operation on rotor."


def test_completion_diagnostic_accepts_missing_or_malformed_optional_details():
    plan = PlanProgram(plans=[])
    attempt = AttemptRecord('a', 'r', 'e', 'physical', {'step_id': 'missing'})
    report = RunReportInteractor(None, None, None)
    for details in ({}, {'context': None, 'native_details': []}, {'context': {'device': 5}}):
        faults = [(attempt, None), (attempt, {'reason': 'culsma.operation.completion_unconfirmed', **details})]
        diagnostic, = report.fault_diagnostics(plan, faults)
        assert diagnostic.message == 'Completion is not confirmed for device operation.'
