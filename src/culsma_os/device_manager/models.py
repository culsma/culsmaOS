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
    setup_required: bool = False
    simulation_scope: str = "station"
    # Driver implementations for this station's execution mode, independent of
    # which instrument instances are configured. None denotes an older plugin.
    instrument_drivers: dict[str, tuple[str, ...]] | None = None
    # Conditions the driver can maintain during pipetting, independent of a
    # centrifuge's ability to establish them during separation.
    transfer_environment_conditions: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.simulation_scope not in {'station', 'run', 'unknown'}:
            raise ValueError('DEVICE_SIMULATION_SCOPE_INVALID')
        if self.simulation_scope == 'run' and self.mode != 'simulation':
            raise ValueError('SIMULATION_SCOPE_REQUIRES_SIMULATION')
        if type(self.setup_required) is not bool:
            raise ValueError("DEVICE_SETUP_CAPABILITY_INVALID")
        if self.supports_transfer is not None and type(self.supports_transfer) is not bool:
            raise ValueError("DEVICE_TRANSFER_CAPABILITY_INVALID")
        drivers = self.instrument_drivers
        if drivers is not None and (not isinstance(drivers, dict)
                or any(not isinstance(kind, str) or not kind.strip()
                       or not isinstance(operations, tuple) or not operations
                       or any(not isinstance(op, str) or not op.strip() for op in operations)
                       or len(set(operations)) != len(operations)
                       for kind, operations in drivers.items())):
            raise ValueError("DEVICE_INSTRUMENT_DRIVERS_INVALID")
        values = self.transfer_requirements
        if (not isinstance(values, tuple) or any(type(v) is not str or not v.strip() for v in values)
                or len(set(values)) != len(values)):
            raise ValueError("DEVICE_TRANSFER_REQUIREMENTS_INVALID")
        values = self.transfer_selection_capabilities
        if (not isinstance(values, tuple) or any(not isinstance(v, str) or not v.strip() for v in values)
                or len(set(values)) != len(values)):
            raise ValueError("DEVICE_TRANSFER_SELECTION_CAPABILITIES_INVALID")


    @staticmethod
    def matching_instruments(instances, kind=None):
        return {name: instance for name, instance in instances.items()
                if kind is None or instance.get('instrument_kind') == kind}

    @staticmethod
    def connected_candidates(instances):
        # With no observation, leave live readiness to the driver at dispatch.
        return {name: instance for name, instance in instances.items()
                if instance.get('connection_state') != 'disconnected'}

    def require_instrument(self, operation, instances, *, legacy_error, kind=None):
        instances = self.matching_instruments(instances, kind)
        if self.instrument_drivers is not None:
            if not any(operation in operations for name, operations in self.instrument_drivers.items()
                       if kind is None or kind == name):
                raise ValueError(f"INSTRUMENT_DRIVER_UNAVAILABLE: No driver provides {kind or operation} in this execution mode.")
            if not instances:
                raise ValueError(f"INSTRUMENT_DEVICE_NOT_CONFIGURED: No device is configured for {kind or operation}.")
        elif not instances:
            raise ValueError(legacy_error)
        available = self.connected_candidates(instances)
        if not available:
            raise ValueError(f"INSTRUMENT_DEVICE_DISCONNECTED: No configured device is connected for {kind or operation}.")
        return available

    def require_transfer(self):
        configured = self.supports_transfer is True or (self.supports_transfer is None and self.instrument_drivers is None)
        instances = {"pipetting": {}} if configured else {}
        self.require_instrument("transfer", instances, legacy_error="TRANSFER_DEVICE_UNSUPPORTED")

    def require_motion(self):
        if self.instrument_drivers is not None:
            instances = {"transport": self.motion_capabilities} if self.motion_capabilities else {}
            self.require_instrument("labware_move", instances, legacy_error="MOTION_ROUTE_UNSUPPORTED")

    def processing_modules(self, intent):
        modules = self.processing_capabilities.get(intent.capability, {})
        kind = getattr(intent, 'instrument_kind', None) if self.instrument_drivers is not None else None
        return self.require_instrument(intent.capability, modules, legacy_error='PROCESSING_MODULE_UNAVAILABLE',
                                       kind=kind)

    def execution_identity(self, station_id):
        return {
            "station_id": station_id,
            "device_id": self.device_id,
            "configuration_revision": self.configuration_revision,
            "calibration_revision": self.calibration_revision,
        }

    def verify_workspace_capabilities(self, catalogue):
        if 'processing_capabilities' not in catalogue:
            return
        if (catalogue.get('device_id') != self.device_id
                or catalogue.get('configuration_revision') != self.configuration_revision
                or catalogue['processing_capabilities'] != self.processing_capabilities):
            raise ValueError('SETUP_DEVICE_CAPABILITIES_MISMATCH: Loading and execution describe different device capabilities.')


class DeviceReadinessPort(Protocol):

    def check_ready(self) -> None: ...

    def restore_consumables(self, consumption: dict[str, int]) -> None: ...


class DeviceAccessPort(Protocol):

    def get(self, device_id: str) -> DeviceConfigurationSnapshot: ...

    def validate_ready(self, context) -> None: ...


@dataclass(frozen=True)
class SimulationLoadingRequest:
    """Initial loading only; execution predictions and final state are excluded."""

    run_id: str
    configuration_revision: str
    plan_fingerprint: str
    loadout: tuple[dict, ...]
    supplies: tuple[dict, ...]


class SimulationLoadingPort(Protocol):
    def configure_simulation_loading(self, request: SimulationLoadingRequest) -> None: ...


class RunScopedSimulationPort(Protocol):
    """Optional simulator capability. Scope selection retains prior run records."""

    simulation_scope: str

    def begin_simulation_run(self, run_id: str) -> None: ...


@dataclass(frozen=True)
class DeviceProfileRequest:
    action: str
    driver: str | None = None
    configuration: dict | None = None
    layout_source: dict | None = None


class DeviceProfileQueryPort(Protocol):
    def describe(self) -> dict: ...
    def validate(self, driver: str, configuration: dict) -> dict: ...
    def export_layout(self, driver: str, configuration: dict) -> dict | None: ...
    def import_layout(self, driver: str, source: dict) -> dict | None: ...
    def program_bindings(self, driver: str, configuration: dict) -> dict | None: ...


class DeviceProfileQueryError(ValueError):
    def __init__(self,code,kind='invalid_request'):
        super().__init__(code);self.code,self.kind=code,kind
