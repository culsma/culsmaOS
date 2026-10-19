from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedContainerRef:
    container_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.container_id, str) or not self.container_id.strip():
            raise ValueError("container_id must be a resolved nonempty identity")


@dataclass(frozen=True)
class SpaceBinding:
    reference: ResolvedContainerRef
    labware: str
    well: str
    capacity_uL: float
    allocation_step_id: str
    carrier_id: str | None = None
    carrier_namespace: str | None = None
    carrier_position: str | None = None
    carrier_geometry: tuple[int, int] | None = None
    carrier_instance_id: str | None = None


@dataclass(frozen=True)
class LayoutSnapshot:
    run_id: str
    revision: str
    bindings: tuple[SpaceBinding, ...]


from typing import Protocol


class WorkspaceAccessPort(Protocol):

    def bind(self, run_id: str, material_state: dict, allocation_steps=()) -> LayoutSnapshot: ...

    def preview(self, run_id: str, material_state: dict, allocation_steps=()) -> LayoutSnapshot: ...

    def validate_snapshot(self, run_id: str, revision: str) -> None: ...


@dataclass(frozen=True)
class CarrierRef:
    namespace: str
    carrier_id: str
    instance_id: str | None = None

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in (self.namespace, self.carrier_id)):
            raise ValueError("MOTION_CARRIER_REFERENCE_INVALID")
        if self.instance_id is not None and (not isinstance(self.instance_id, str) or not self.instance_id):
            raise ValueError("MOTION_CARRIER_REFERENCE_INVALID")


@dataclass(frozen=True)
class LabwareMoveIntent:
    step_id: str
    carrier: CarrierRef
    labware: str
    source: str
    destination: str
    position_revision: int


class MotionDevicePort(Protocol):
    def prepare_labware_move(self, intent): ...
    def describe_labware_move(self, prepared): ...


class ProcessingPlacementPort(Protocol):
    def project_move(self, labware: str, source: str, destination: str, projected): ...

    def select_module(self, labware: str, modules: tuple[str, ...], positions: dict | None = None) -> str: ...

    def require_module(self, labware: str, module: str, positions: dict | None = None) -> None: ...


@dataclass(frozen=True)
class WorkspaceAddress:
    labware: str
    well: str


class ProgramWorkspacePort(Protocol):
    def workspace_for_run(self, run_id: str) -> dict | None: ...


@dataclass(frozen=True)
class StationConfigurationRequest:
    action: str
    draft_id: str | None = None
    revision: int | None = None
    title: str | None = None
    driver: str | None = None
    configuration: dict | None = None


class ConfigurationError(ValueError):
    def __init__(self, code, kind='invalid_request'):
        super().__init__(code)
        self.code, self.kind = code, kind


@dataclass(frozen=True)
class StationConfigurationDraft:
    draft_id: str
    revision: int
    title: str
    driver: str
    fingerprint: str
    configuration_json: str

    @classmethod
    def from_record(cls, record):
        import json
        return cls(record['draft_id'],record['revision'],record['title'],record['driver'],
                   record['fingerprint'],json.dumps(record['configuration'],allow_nan=False))

    def as_dict(self):
        import json
        return {'draft_id':self.draft_id,'revision':self.revision,'title':self.title,
                'driver':self.driver,'fingerprint':self.fingerprint,
                'configuration':json.loads(self.configuration_json)}
