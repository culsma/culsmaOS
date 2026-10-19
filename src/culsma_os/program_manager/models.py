from dataclasses import dataclass
from typing import Protocol
from culsma.pipeline.plan_nodes import PlanProgram
from culsma.runtime.state import RuntimeState
from pathlib import Path
from typing import Any
from culsma.pipeline.plan_nodes import PlanStep
from culsma.runtime.material.result import MaterialUpdateResult
from culsma.runtime.executor import RunResult
from dataclasses import field
from culsma_os.resource_manager.models import RunReleaseConfirmation


@dataclass(frozen=True)
class RunRequest:
    plan: PlanProgram
    state: RuntimeState


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
    checkpoint: str
    revision: int = 0
    error: str | None = None
    body_outcome: str | None = None
    body_error: str | None = None


class SemanticHostPort(Protocol):

    def create(self, plan, state, scope_id) -> str: ...

    def advance(self, checkpoint: str) -> str: ...

    def resume(self, checkpoint: str, resolution) -> str: ...

    def pending(self, checkpoint: str): ...

    def restore(self, checkpoint: str): ...

    def result(self, checkpoint: str): ...


@dataclass(frozen=True)
class RunStateEvent:
    event_id: str
    run_id: str
    status: str
    revision: int


class OperationPreflightPort(Protocol):
    def preflight(self, pending, space, device, scope_id, allocation_steps, physical_positions=None): ...


class ConditionPreflightPort(Protocol):
    def before_effect(self, pending, retained, projected): ...

    def after_effect(self, pending, allocations, retained, projected): ...

    def release(self, retained, projected): ...


class ProgramPreflightPort(Protocol):
    def inspect(self, plan, state, scope_id): ...


class RunConflict(ValueError):
    pass


@dataclass(frozen=True)
class PreparedRuntimeStep:
    runtime_step: PlanStep
    driver_step: PlanStep
    material_result: MaterialUpdateResult | None


@dataclass(frozen=True)
class PendingEffect:
    effect_id: str
    prepared: PreparedRuntimeStep
    before_material_state: dict[str, Any]


@dataclass(frozen=True)
class EffectResolution:
    effect_id: str
    evidence_id: str
    registration_id: str
    proposed_state_fingerprint: str
    mode: str
    code: str
    payload: dict[str, Any]

    def __post_init__(self):
        if not all(
            (
                self.effect_id,
                self.evidence_id,
                self.registration_id,
                self.proposed_state_fingerprint,
            )
        ):
            raise ValueError("HOST_RESOLUTION_UNREGISTERED")
        if self.mode != "simulation":
            raise ValueError("HOST_PHYSICAL_RESOLUTION_UNSUPPORTED")


@dataclass(frozen=True)
class HostBuildContext:
    database_path: Path
    driver_name: str
    config_path: Path | None
    artifacts_dir: Path
    station_id: str | None = None
    station_root: Path | None = None
    device_state_dir: Path | None = None
    workspace_config_path: Path | None = None


class RunHostPort(Protocol):
    def execute(self, plan: PlanProgram, state: RuntimeState) -> RunResult: ...
    def close(self) -> None: ...


class RunHostFactory(Protocol):
    def build(self, context: HostBuildContext) -> RunHostPort: ...


class HostContractError(ValueError):
    pass


@dataclass(frozen=True)
class RecordedEffect:
    effect_id: str
    prepared_fingerprint: str
    before_fingerprint: str
    resolution: EffectResolution


@dataclass(frozen=True)
class HostedRunResult(RunResult):
    settled: bool = False

    @property
    def ok(self):
        return self.settled and super().ok


class HostedEffectPending(Exception):
    pass


@dataclass(frozen=True)
class CommandRequest:
    input_paths: list[Path]
    fail_ops: set[str] = field(default_factory=set)
    material_state_path: Path | None = None
    inventory_check: bool | dict[str, Any] | None = None
    inventory_path: Path | None = None
    library_roots: list[Path] = field(default_factory=list)
    driver_name: str = "stub"
    driver_config_path: Path | None = None
    driver_artifacts_dir: Path | None = None
    execution_mode: str = "os"
    host_database_path: Path | None = None
    station_id: str | None = None
    workspace_config_path: Path | None = None


@dataclass(frozen=True)
class PendingEffectGroup:
    effect_id: str
    step_id: str
    members: tuple[PendingEffect, ...]
    source_member_ids: tuple[str, ...]

    @property
    def before_material_state(self):
        return self.members[0].before_material_state


@dataclass(frozen=True)
class GroupEffectResolution:
    effect_id: str
    members: tuple[EffectResolution, ...]


@dataclass(frozen=True)
class RecordedEffectGroup:
    effect_id: str
    prepared_fingerprint: str
    resolution: GroupEffectResolution


@dataclass(frozen=True)
class ProjectedMaterialEffect:
    effect_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    semantic_state_fingerprint: str


class GroupProjectionPort(Protocol):
    def prepare(self, pending: PendingEffectGroup, waves) -> tuple[ProjectedMaterialEffect, ...]: ...

    def certificate(self, pending: PendingEffectGroup, projections) -> dict: ...


@dataclass(frozen=True)
class RunControlRequest:
    action: str
    run_id: str
    context: HostBuildContext


@dataclass(frozen=True)
class RunFinalizationProof:
    run_id: str
    revision: int
    body_outcome: str
    evidence_ids: tuple[str, ...]
    release: "RunReleaseConfirmation | None"


@dataclass(frozen=True)
class CompiledProgram:
    frontend: Any
    ir: Any
    semantic: Any
    typed: Any
    plan: PlanProgram
    state: RuntimeState
    initial_material_state: dict


@dataclass(frozen=True)
class QueueSubmission:
    request_id: str
    fingerprint: str
    source: str


@dataclass(frozen=True)
class QueuedRun:
    sequence: int
    run_id: str
    source: str
    request_id: str
    fingerprint: str


@dataclass(frozen=True)
class ResidentCommand:
    action: str
    run_id: str | None = None
    source: Path | None = None
    material_state: Path | None = None
    library_roots: tuple[Path, ...] = ()
    request_id: str | None = None


class ResidentAdmissionError(ValueError):
    def __init__(self, code, diagnostics=()):
        super().__init__(code)
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True)
class ConsoleReadRequest:
    resource: str
    run_id: str | None = None


@dataclass(frozen=True)
class ConsoleReadResponse:
    resource: str
    observed_at: str
    data: dict[str, Any]

    def as_dict(self):
        return {"schema": "culsma_console_v1", "ok": True, "resource": self.resource,
                "observed_at": self.observed_at, "source": "resident_service",
                "consistency": "independent_resident_reads", "data": self.data}


class ConsoleReadError(ValueError):
    def __init__(self, code: str, kind: str):
        super().__init__(code)
        self.code, self.kind = code, kind


class ResidentReadPort(Protocol):
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]: ...
