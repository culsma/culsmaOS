"""Observe durable evidence without ingesting receipts or synchronizing usage."""
from ..models import AttemptObservation, DeviceEvidenceObservation, RunJournalObservation
from ..repositories.inspection import EvidenceInspectionRepository


class EvidenceInspectionInteractor:
    def __init__(self, repository: EvidenceInspectionRepository):
        self.repository = repository

    def inspect(self, device_id):
        evidence = {e.effect_id: e for e in self.repository.evidence()}
        operations, consumption, identities = [], {}, []
        for attempt in self.repository.attempts(device_id):
            receipt = evidence.get(attempt.effect_id)
            if receipt is not None and (receipt.attempt_id, receipt.run_id, receipt.mode) != (
                    attempt.attempt_id, attempt.run_id, attempt.mode):
                receipt = None
            operations.append(AttemptObservation(attempt, receipt))
            if receipt is not None and receipt.mode == 'simulation':
                identities.append(receipt.evidence_id)
                for name, amount in receipt.consumed_resources.items():
                    consumption[name] = consumption.get(name, 0) + amount
        return DeviceEvidenceObservation(tuple(operations), consumption, tuple(identities),
            'recorded' if self.repository.available() else 'unavailable')


    def inspect_run(self, run_id):
        evidence = {e.effect_id: e for e in self.repository.evidence()}
        operations, mismatched = [], []
        for attempt in self.repository.attempts_for_run(run_id):
            receipt = evidence.get(attempt.effect_id)
            if receipt is not None and (receipt.attempt_id, receipt.run_id, receipt.mode) != (
                    attempt.attempt_id, attempt.run_id, attempt.mode):
                mismatched.append(attempt.effect_id)
                receipt = None
            operations.append(AttemptObservation(attempt, receipt))
        return RunJournalObservation(tuple(operations), self.repository.logical_for_run(run_id),
            tuple(mismatched), 'recorded' if self.repository.available() else 'unavailable')
