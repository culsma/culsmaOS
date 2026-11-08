from dataclasses import dataclass, field
from ..execution_models import EnvironmentCondition
from culsma.pipeline.plan_nodes import PlanStep
from math import isfinite
from culsma.common.source import Span
from culsma_os.workspace_manager.models import ResolvedContainerRef
from culsma_os.program_manager.models import PendingEffect


@dataclass(frozen=True)
class TransferRequest:
    run_id: str
    pending: PendingEffect
    allocation_steps: tuple[PlanStep, ...] = ()


@dataclass(frozen=True)
class TransferAliquot:
    source: ResolvedContainerRef
    volume_uL: float

    def __post_init__(self) -> None:
        if not isinstance(self.source, ResolvedContainerRef):
            raise TypeError("source must be ResolvedContainerRef")
        if (
            isinstance(self.volume_uL, bool)
            or not isinstance(self.volume_uL, (int, float))
            or not isfinite(self.volume_uL)
            or self.volume_uL <= 0
        ):
            raise ValueError("volume_uL must be positive and finite")


@dataclass(frozen=True)
class TransferIntent:
    step_id: str
    target: ResolvedContainerRef
    aliquots: tuple[TransferAliquot, ...]
    span: Span | None = None
    requirements: tuple[str, ...] = ()
    constraint_options: tuple[str, ...] = ()
    environment_requirements: tuple[str, ...] = ()
    environment_conditions: tuple[EnvironmentCondition, ...] = field(default=(), kw_only=True)
    environment_targets: tuple[ResolvedContainerRef, ...] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        if (not isinstance(self.environment_conditions, tuple)
                or not all(isinstance(c, EnvironmentCondition) for c in self.environment_conditions)
                or not isinstance(self.environment_targets, tuple)
                or not all(isinstance(t, ResolvedContainerRef) for t in self.environment_targets)
                or bool(self.environment_conditions) != bool(self.environment_targets)):
            raise ValueError("TRANSFER_ENVIRONMENT_INVALID")
        if not isinstance(self.step_id, str) or not self.step_id.strip():
            raise ValueError("step_id must be nonempty")
        if not isinstance(self.target, ResolvedContainerRef):
            raise TypeError("target must be ResolvedContainerRef")
        if (
            not isinstance(self.aliquots, tuple)
            or not self.aliquots
            or not all(isinstance(a, TransferAliquot) for a in self.aliquots)
        ):
            raise TypeError("aliquots must be a nonempty tuple of TransferAliquot")
        if self.span is not None and not isinstance(self.span, Span):
            raise TypeError("span must be Span")
        for values in (
            self.requirements,
            self.constraint_options,
            self.environment_requirements,
        ):
            if not isinstance(values, tuple) or not all(
                isinstance(v, str) and v.strip() for v in values
            ):
                raise TypeError(
                    "support requirements must be immutable nonempty string tuples"
                )


@dataclass(frozen=True)
class TransferGroupIntent:
    step_id: str
    members: tuple[TransferIntent, ...]


@dataclass(frozen=True)
class TransferExecutionDecision:
    intent: TransferIntent | None


@dataclass(frozen=True)
class MagneticFlowthroughTransferIntent(TransferIntent):
    producer_step_id: str = ""


from typing import Protocol, ClassVar


class TransferSelectionPort(Protocol):
    def handles(self, pending: PendingEffect) -> bool: ...
    def resolve_execution(self, pending: PendingEffect) -> TransferExecutionDecision: ...


@dataclass(frozen=True)
class CentrifugeFractionTransferIntent(TransferIntent):
    producer_step_id: str = ""
    selected_slot: str = "0"


@dataclass(frozen=True)
class CentrifugeSupernatantTransferIntent(CentrifugeFractionTransferIntent):
    selection_kind: ClassVar[str] = "centrifuge_supernatant"


@dataclass(frozen=True)
class CentrifugePelletTransferIntent(CentrifugeFractionTransferIntent):
    selection_kind: ClassVar[str] = "centrifuge_pellet"
    selected_slot: str = "1"
