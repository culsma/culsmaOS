"""Read-only access to EventJournal-owned attempt and receipt tables."""
import json
from typing import Protocol
from ..models import AttemptRecord, ExecutionEvidence


class EvidenceInspectionRepository(Protocol):
    def attempts(self, device_id) -> tuple[AttemptRecord, ...]: ...
    def evidence(self) -> tuple[ExecutionEvidence, ...]: ...
    def available(self) -> bool: ...


class SqliteEvidenceInspectionRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def available(self):
        return {'os_attempts', 'os_evidence'} <= self.snapshot.tables

    def attempts(self, device_id):
        records = (json.loads(row[0]) for row in self.snapshot.rows(
            "os_attempts", "SELECT record FROM os_attempts ORDER BY attempt_id"))
        return tuple(AttemptRecord(**r) for r in records if r['context']['device_id'] == device_id)

    def evidence(self):
        return tuple(ExecutionEvidence(**json.loads(row[0])) for row in self.snapshot.rows(
            "os_evidence", "SELECT record FROM os_evidence ORDER BY evidence_id"))
