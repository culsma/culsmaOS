from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryDecision:
    run_id: str
    action: str
    reason: str
