from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionEvidence:
    evidence_id: str
    run_id: str
    effect_id: str
    attempt_id: str
    mode: str
    outcome: str
    payload: dict[str, Any]
    consumed_resources: dict[str, int]


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    run_id: str
    effect_id: str
    mode: str
    context: dict[str, Any]


@dataclass(frozen=True)
class LogicalCompletion:
    completion_id: str
    run_id: str
    effect_id: str
    mode: str
    prepared_fingerprint: str
    before_fingerprint: str
    proposed_state_fingerprint: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AttemptObservation:
    attempt: AttemptRecord
    evidence: ExecutionEvidence | None


@dataclass(frozen=True)
class DeviceEvidenceObservation:
    operations: tuple[AttemptObservation, ...]
    known_consumption: dict[str, int]
    evidence_ids: tuple[str, ...]
    accounting: str = 'recorded'
