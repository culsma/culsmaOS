from dataclasses import dataclass
from culsma_os.program_manager.models import EffectResolution, GroupEffectResolution


@dataclass(frozen=True)
class MaterialCommitReceipt:
    registration_id: str
    effect_id: str
    evidence_id: str
    version: int
    proposed_state_fingerprint: str
    semantic_state_fingerprint: str | None = None


@dataclass(frozen=True)
class ReconciliationResult:
    ready: bool
    resolution: EffectResolution | GroupEffectResolution | None = None
    reason: str | None = None


@dataclass(frozen=True)
class MaterialCommitProposal:
    effect_id: str
    evidence_id: str
    before: dict
    after: dict
    fingerprint: str
    semantic_state_fingerprint: str | None = None
