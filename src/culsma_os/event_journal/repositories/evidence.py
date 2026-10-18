from dataclasses import asdict
import json
from typing import Protocol
from ..models import ExecutionEvidence, AttemptRecord, LogicalCompletion


class EvidenceRepository(Protocol):
    def attempts_for_device(self, device_id): ...

    def record_logical_completion(self, completion: LogicalCompletion) -> None: ...

    def find_logical_completion(self, effect_id: str) -> LogicalCompletion | None: ...

    def record_intent(self, attempt: AttemptRecord) -> None: ...

    def find_attempt(self, effect_id: str) -> AttemptRecord | None: ...

    def ingest(self, evidence: ExecutionEvidence) -> None: ...

    def find_evidence(self, effect_id: str) -> ExecutionEvidence | None: ...

    def for_device(self, device_id: str) -> tuple[ExecutionEvidence, ...]: ...

    def find_attempt_by_id(self, attempt_id: str) -> AttemptRecord | None: ...

    def attempts_for_run(self, run_id: str) -> tuple[AttemptRecord, ...]: ...


class SqliteEvidenceRepository:

    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_attempts(attempt_id TEXT PRIMARY KEY,effect_id TEXT UNIQUE,record TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_logical_completions(effect_id TEXT PRIMARY KEY,record TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_evidence(evidence_id TEXT PRIMARY KEY,effect_id TEXT UNIQUE,record TEXT)"
            )

    def record_intent(self, attempt):
        payload = json.dumps(asdict(attempt), sort_keys=True)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.find_logical_completion(attempt.effect_id) is not None:
                raise ValueError("LOGICAL_PHYSICAL_CONFLICT")
            old = self.connection.execute(
                "SELECT record FROM os_attempts WHERE effect_id=?", (attempt.effect_id,)
            ).fetchone()
            if old and old[0] != payload:
                raise ValueError("ATTEMPT_CONFLICT")
            self.connection.execute(
                "INSERT OR IGNORE INTO os_attempts VALUES(?,?,?)",
                (attempt.attempt_id, attempt.effect_id, payload),
            )

    def find_attempt(self, effect_id):
        row = self.connection.execute(
            "SELECT record FROM os_attempts WHERE effect_id=?", (effect_id,)
        ).fetchone()
        return AttemptRecord(**json.loads(row[0])) if row else None

    def ingest(self, evidence):
        attempt = self.find_attempt(evidence.effect_id)
        if attempt is None or (attempt.attempt_id, attempt.run_id, attempt.mode) != (
            evidence.attempt_id,
            evidence.run_id,
            evidence.mode,
        ):
            raise ValueError("EVIDENCE_ATTEMPT_MISMATCH")
        payload = json.dumps(asdict(evidence), sort_keys=True)
        with self.connection:
            old = self.connection.execute(
                "SELECT record FROM os_evidence WHERE effect_id=?",
                (evidence.effect_id,),
            ).fetchone()
            if old and old[0] != payload:
                raise ValueError("EVIDENCE_CONFLICT")
            self.connection.execute(
                "INSERT OR IGNORE INTO os_evidence VALUES(?,?,?)",
                (evidence.evidence_id, evidence.effect_id, payload),
            )

    def find_evidence(self, effect_id):
        row = self.connection.execute(
            "SELECT record FROM os_evidence WHERE effect_id=?", (effect_id,)
        ).fetchone()
        return ExecutionEvidence(**json.loads(row[0])) if row else None

    def for_device(self, device_id):
        rows = self.connection.execute(
            "SELECT e.record,a.record FROM os_evidence e JOIN os_attempts a ON e.effect_id=a.effect_id"
        )
        return tuple(
            (
                ExecutionEvidence(**json.loads(e))
                for e, a in rows
                if json.loads(a)["context"]["device_id"] == device_id
            )
        )

    def find_attempt_by_id(self, attempt_id):
        row = self.connection.execute(
            "SELECT record FROM os_attempts WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        return AttemptRecord(**json.loads(row[0])) if row else None


    def attempts_for_run(self, run_id):
        rows = self.connection.execute("SELECT record FROM os_attempts")
        return tuple(AttemptRecord(**value) for row in rows if (value := json.loads(row[0]))["run_id"] == run_id)


    def record_logical_completion(self, completion):
        payload = json.dumps(asdict(completion), sort_keys=True)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.find_attempt(completion.effect_id) is not None:
                raise ValueError("LOGICAL_PHYSICAL_CONFLICT")
            old = self.find_logical_completion(completion.effect_id)
            if old is not None and old != completion:
                raise ValueError("LOGICAL_COMPLETION_CONFLICT")
            self.connection.execute("INSERT OR IGNORE INTO os_logical_completions VALUES(?,?)",
                                    (completion.effect_id, payload))

    def find_logical_completion(self, effect_id):
        row = self.connection.execute("SELECT record FROM os_logical_completions WHERE effect_id=?", (effect_id,)).fetchone()
        return LogicalCompletion(**json.loads(row[0])) if row else None

    def attempts_for_device(self, device_id):
        rows = self.connection.execute('SELECT record FROM os_attempts ORDER BY attempt_id')
        return tuple(AttemptRecord(**value) for row in rows
                     if (value := json.loads(row[0]))['context']['device_id'] == device_id)
