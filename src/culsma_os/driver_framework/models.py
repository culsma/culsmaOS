from dataclasses import dataclass
from typing import Any, Protocol
from culsma_os.processing_engine.models import ThermalHoldIntent, OrbitalShakeIntent, CentrifugeIntent, MagneticSeparationIntent, MagneticReleaseIntent
from culsma_os.program_manager.models import PendingEffect
from culsma.pipeline.plan_nodes import PlanStep
from culsma_os.transfer_engine.models import TransferIntent, TransferGroupIntent
from pathlib import Path
from dataclasses import field
from typing import ContextManager
from culsma.driver.base import Driver
from culsma.pipeline.plan_nodes import PlanProgram
from culsma.runtime.state import RuntimeState
from culsma_os.workspace_manager.models import ResolvedContainerRef, LabwareMoveIntent, SpaceBinding


@dataclass(frozen=True)
class MaterialExpectation:
    reference: ResolvedContainerRef
    volume_uL: float


@dataclass(frozen=True)
class PlanContext:
    run_id: str
    device_id: str
    mode: str
    configuration_revision: str
    layout_revision: str
    calibration_revision: str
    resource_ids: tuple[str, ...]
    expected_material: tuple[MaterialExpectation, ...] = ()


class MaterialExpectationPort(Protocol):
    def validate_material(self, expectations, bindings) -> None: ...


@dataclass(frozen=True)
class BatchOperation:
    effect_id: str
    intent: LabwareMoveIntent | TransferIntent | ThermalHoldIntent | OrbitalShakeIntent | CentrifugeIntent | MagneticSeparationIntent | MagneticReleaseIntent
    bindings: tuple[SpaceBinding, ...]


@dataclass(frozen=True)
class ExecutionBatchIntent:
    step_id: str
    operations: tuple[BatchOperation, ...]


@dataclass(frozen=True)
class PreparedDevicePlan:
    effect_id: str
    intent: LabwareMoveIntent | TransferIntent | ThermalHoldIntent | OrbitalShakeIntent | CentrifugeIntent | MagneticSeparationIntent | MagneticReleaseIntent | ExecutionBatchIntent
    context: PlanContext
    vendor_plan: Any
    description: dict[str, Any]


class DeviceExecutionPort(Protocol):

    def prepare(self, intent, bindings): ...

    def describe(self, plan) -> dict: ...

    def execute(self, plan, attempt_id): ...

    def restore_consumables(self, count): ...

    def check_ready(self): ...

    def close(self): ...


@dataclass(frozen=True)
class CompilationEvidence:
    result: Any
    status: str = "compiled"
    physical_execution_supported: bool = False


class CompilationPort(Protocol):

    def compile(self, request): ...


@dataclass(frozen=True)
class DeviceFaultContext:
    device: str | None = None
    module: str | None = None
    channel: str | None = None
    planned_location: str | None = None
    reported_location: str | None = None
    requested: float | None = None
    available: float | None = None
    unit: str | None = None


@dataclass(frozen=True)
class DeviceStopObservation:
    state: str = 'unknown'
    scope: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True)
class DeviceFault:
    code: str
    source: str
    execution_state: str
    operation_id: str | None = None
    location: str | None = None
    native_details: dict[str, Any] = field(default_factory=dict)
    schema: str = 'culsma_device_fault_v1'
    reason: str | None = None
    basis: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    stop_observation: dict[str, Any] = field(default_factory=dict)


class DeviceFaultMappingPort(Protocol):
    def normalize(self, payload: dict) -> list[dict]: ...
    def preparation(self, error: Exception, operation_id: str) -> list[dict]: ...


@dataclass(frozen=True)
class DeviceReceipt:
    outcome: str
    mode: str
    step_id: str
    configuration_revision: str
    payload: dict[str, Any]
    consumed_resources: dict[str, int]

    @property
    def faults(self) -> tuple[DeviceFault, ...]:
        return tuple(DeviceFault(**value) for value in self.payload.get('faults', ()))


class DeviceReceiptMapper(Protocol):

    def map(self, plan: PreparedDevicePlan, payload: dict) -> DeviceReceipt: ...


class DriverGatewayPort(Protocol):

    def prepare(
        self, effect_id: str, intent: TransferIntent, context: PlanContext, bindings,
        completion_unit: str = "operation"
    ) -> PreparedDevicePlan: ...

    def prepare_processing(self, effect_id: str, intent: ThermalHoldIntent | OrbitalShakeIntent | CentrifugeIntent | MagneticSeparationIntent | MagneticReleaseIntent, context: PlanContext, bindings) -> PreparedDevicePlan: ...

    def prepare_motion(self, effect_id: str, intent: LabwareMoveIntent, context: PlanContext) -> PreparedDevicePlan: ...

    def execute(
        self, plan: PreparedDevicePlan, permit, attempt_id: str
    ) -> DeviceReceipt: ...


@dataclass(frozen=True)
class DriverBuildContext:
    plan: PlanProgram
    state: RuntimeState
    config_path: Path | None = None
    artifacts_dir: Path = Path("run-artifacts/drivers")
    fail_ops: frozenset[str] = field(default_factory=frozenset)


class DriverFactory(Protocol):
    def open(self, context: DriverBuildContext) -> ContextManager[Driver]: ...


class DriverLoadError(ValueError):
    """Host setup failure; no language or material semantics are changed."""


class DevicePreparationError(ValueError):
    """Transport-neutral preparation rejection with the plugin diagnostic code."""

    def __init__(self, code: str, message: str, faults=()):
        self.faults = tuple(faults)
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class PreparedTransferGroup:
    effect_id: str
    intent: TransferGroupIntent
    context: PlanContext
    members: tuple[PreparedDevicePlan, ...]
    description: dict[str, Any]
    vendor_plan: Any = None
    waves: tuple = ()


class GroupGatewayPort(DriverGatewayPort, Protocol):
    supports_collective_execution: bool

    def prepare_collective_group(self, effect_id, step_id, member_effect_ids, intents, context, bindings) -> PreparedTransferGroup: ...

    def execute_collective_group(self, group: PreparedTransferGroup, permit, attempt_id: str) -> DeviceReceipt: ...

    def execute_group_wave(self, group, wave, permit, group_attempt_id, wave_attempt_id) -> DeviceReceipt: ...

    def execute_group_member(self, group: PreparedTransferGroup, member: PreparedDevicePlan,
                             permit, group_attempt_id: str, member_attempt_id: str) -> DeviceReceipt: ...


class CollectiveDeviceExecutionPort(DeviceExecutionPort, Protocol):
    supports_collective_execution: bool

    def prepare_group(self, group_id, intents, bindings): ...

    def describe_group(self, plan) -> dict: ...

    def execute_group(self, plan, attempt_id) -> dict: ...

    def wave_plans(self, plan): ...

    def execute_group_wave(self, plan, wave, attempt_id) -> dict: ...


@dataclass(frozen=True)
class PreparedDeviceWave:
    effect_id: str
    intent: TransferGroupIntent
    context: PlanContext
    members: tuple[PreparedDevicePlan, ...]
    description: dict[str, Any]
    vendor_plan: Any


@dataclass(frozen=True)
class OperationPreparationRequest:
    run_id: str
    pending: PendingEffect
    allocation_steps: tuple[PlanStep, ...] = ()


class OperationPreparationPort(Protocol):
    def prepare(self, request: OperationPreparationRequest) -> PreparedDevicePlan: ...


class ProcessingExecutionPort(DeviceExecutionPort, Protocol):
    def prepare_processing(self, intent, bindings): ...
    def describe_processing(self, plan) -> dict: ...


class DeviceProfilePort(Protocol):
    def describe(self) -> dict: ...
    def validate(self, configuration: dict) -> dict: ...


class ProgramBindingProfilePort(Protocol):
    """Optional offline projection; concrete configuration keys stay external."""
    def program_bindings(self, configuration: dict) -> dict: ...


class LayoutExportProfilePort(Protocol):
    """Optional vendor-owned native layout export; no station activation."""
    def export_layout(self, configuration: dict) -> dict: ...


class LayoutExportError(ValueError):
    code = 'PROFILE_LAYOUT_EXPORT_INVALID'


class BatchDeviceExecutionPort(DeviceExecutionPort, Protocol):
    def prepare_batch(self, step_id: str, operations: tuple[BatchOperation, ...]): ...
    def describe_batch(self, plan) -> dict: ...


class LayoutImportProfilePort(Protocol):
    """Optional vendor parser; returns detached configuration and conversion diagnostics."""
    def import_layout(self, content: bytes, source_name: str) -> dict: ...


class LayoutImportError(ValueError):
    code = 'PROFILE_LAYOUT_IMPORT_INVALID'


class ConfiguredLayoutReadPort(Protocol):
    """Offline projection only; the returned descriptor contains no connection secrets."""
    def execute(self, path: Path) -> dict: ...


class LabwareEditorPort(Protocol):
    """Optional offline capability on an OS device factory.

    Catalogue exposes only declarative choices. Prepare returns a detached full
    configuration and generic diagram, never writes files or contacts hardware.
    The resident retains configuration ownership; the UI receives no native data.
    """
    def catalogue(self, path: Path) -> dict: ...
    def prepare(self, path: Path, change: dict) -> dict: ...


class WorkspaceCatalogueReadPort(Protocol):
    """Offline declared positions/supplies. Implementations must not connect to hardware."""
    def execute(self, path: Path) -> dict: ...
