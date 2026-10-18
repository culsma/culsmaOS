from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExecutionFeedbackCapabilities:
    """Terminal receipt units, independent of instrument channel count."""

    completion_units: tuple[str, ...] = ("operation",)

    def __post_init__(self):
        allowed = {"operation", "member", "batch", "wave"}
        if (not isinstance(self.completion_units, tuple)
                or any(not isinstance(unit, str) or unit not in allowed for unit in self.completion_units)
                or len(set(self.completion_units)) != len(self.completion_units)):
            raise ValueError("FEEDBACK_CAPABILITIES_INVALID")


@dataclass(frozen=True)
class DeviceConfigurationSnapshot:
    device_id: str
    mode: str
    configuration_revision: str
    shared_resources: tuple[str, ...]
    calibration_revision: str = "simulation"
    consumable_capacities: dict[str, int] = field(default_factory=dict)
    labware_geometries: dict[str, tuple[int, int]] = field(default_factory=dict)
    transfer_channels: int = 1
    processing_capabilities: dict = field(default_factory=dict)
    feedback_capabilities: ExecutionFeedbackCapabilities | None = None
    transfer_selection_capabilities: tuple[str, ...] = ()
    supports_transfer: bool | None = None
    motion_capabilities: dict = field(default_factory=dict)
    transfer_requirements: tuple[str, ...] = ()

    def __post_init__(self):
        if self.supports_transfer is not None and type(self.supports_transfer) is not bool:
            raise ValueError("DEVICE_TRANSFER_CAPABILITY_INVALID")
        values = self.transfer_requirements
        if (not isinstance(values, tuple) or any(type(v) is not str or not v.strip() for v in values)
                or len(set(values)) != len(values)):
            raise ValueError("DEVICE_TRANSFER_REQUIREMENTS_INVALID")
        values = self.transfer_selection_capabilities
        if (not isinstance(values, tuple) or any(not isinstance(v, str) or not v.strip() for v in values)
                or len(set(values)) != len(values)):
            raise ValueError("DEVICE_TRANSFER_SELECTION_CAPABILITIES_INVALID")


class DeviceReadinessPort(Protocol):

    def check_ready(self) -> None: ...

    def restore_consumables(self, consumption: dict[str, int]) -> None: ...


class DeviceAccessPort(Protocol):

    def get(self, device_id: str) -> DeviceConfigurationSnapshot: ...

    def validate_ready(self, context) -> None: ...
