"""Observe durable evidence without ingesting receipts or synchronizing usage."""
from ..models import AttemptObservation, DeviceEvidenceObservation, RunJournalObservation
from ..repositories.inspection import EvidenceInspectionRepository


class EvidenceInspectionInteractor:
    def __init__(self, repository: EvidenceInspectionRepository):
        self.repository = repository

    def inspect(self, device_id, mode="simulation"):
        evidence = {e.effect_id: e for e in self.repository.evidence()}
        stops = self.repository.stops()
        operations, consumption, identities = [], {}, []
        reserved = {}
        for attempt in self.repository.attempts(device_id):
            receipt = evidence.get(attempt.effect_id)
            if receipt is not None and (receipt.attempt_id, receipt.run_id, receipt.mode) != (
                    attempt.attempt_id, attempt.run_id, attempt.mode):
                receipt = None
            stop = stops.get(attempt.attempt_id)
            operations.append(AttemptObservation(attempt, receipt, stop))
            if stop and attempt.mode == mode:
                identities.append(stop['stop_id'])
                for name, amount in stop['reserved_consumption'].items():
                    reserved[name] = reserved.get(name, 0) + amount
            if receipt is not None and receipt.mode == mode:
                identities.append(receipt.evidence_id)
                for name, amount in receipt.consumed_resources.items():
                    consumption[name] = consumption.get(name, 0) + amount
        return DeviceEvidenceObservation(tuple(operations), consumption, tuple(identities),
            'recorded' if self.repository.available() else 'unavailable', reserved)


    def inspect_run(self, run_id):
        evidence = {e.effect_id: e for e in self.repository.evidence()}
        stops = self.repository.stops()
        operations, mismatched = [], []
        for attempt in self.repository.attempts_for_run(run_id):
            receipt = evidence.get(attempt.effect_id)
            if receipt is not None and (receipt.attempt_id, receipt.run_id, receipt.mode) != (
                    attempt.attempt_id, attempt.run_id, attempt.mode):
                mismatched.append(attempt.effect_id)
                receipt = None
            operations.append(AttemptObservation(attempt, receipt, stops.get(attempt.attempt_id)))
        return RunJournalObservation(tuple(operations), self.repository.logical_for_run(run_id),
            tuple(mismatched), 'recorded' if self.repository.available() else 'unavailable')
