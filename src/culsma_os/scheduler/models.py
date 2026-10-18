from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OperationRequest:
    run_id: str
    effect_id: str
    status: str = "queued"


class OperationConditionPort(Protocol):
    def before_effect(self, run_id, pending) -> bool: ...
