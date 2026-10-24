from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING
from enum import Enum
from culsma_os.program_manager.models import RunRecord


@dataclass(frozen=True)
class OperationRequest:
    run_id: str
    effect_id: str
    status: str = "queued"


class OperationConditionPort(Protocol):
    def before_effect(self, run_id, pending) -> bool: ...


class ExecutionMode(str, Enum):
    STEPWISE = "stepwise"
    BATCH = "batch"


class RunExecutionPort(Protocol):
    """Advance a run through OS coordination, including its execution safeguards."""

    def execute(self, run_id: str) -> RunRecord: ...


if TYPE_CHECKING:
    from culsma_os.recovery_manager.models import RecoveryDecision


class ExecutionRecoveryPort(Protocol):
    def reconcile(self, run_id: str) -> "RecoveryDecision | None": ...
