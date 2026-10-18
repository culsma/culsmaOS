from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar, Protocol
from culsma_os.program_manager.models import PendingEffect
from culsma_os.workspace_manager.models import ResolvedContainerRef


@dataclass(frozen=True)
class ProcessingMaterialVolume:
    reference: ResolvedContainerRef
    volume_uL: float | None


@dataclass(frozen=True)
class ThermalHoldIntent:
    capability: ClassVar[str] = "thermal_hold"
    step_id: str
    targets: tuple[ResolvedContainerRef, ...]
    temperature_celsius: float
    duration_seconds: float
    material_volumes: tuple[ProcessingMaterialVolume, ...] = ()


@dataclass(frozen=True)
class OrbitalShakeIntent:
    capability: ClassVar[str] = "orbital_shake"
    step_id: str
    targets: tuple[ResolvedContainerRef, ...]
    rate_rpm: int
    duration_seconds: float


@dataclass(frozen=True)
class ProcessingMethodProfile:
    profile_id: str
    revision: str
    duration_seconds: float


@dataclass(frozen=True)
class CentrifugeSeparationIntent:
    capability: ClassVar[str] = "centrifuge"
    program_kind: ClassVar[str] = "centrifuge_program"
    step_id: str
    targets: tuple[ResolvedContainerRef, ...]
    drive_value: float
    drive_unit: str


@dataclass(frozen=True)
class CentrifugeIntent:
    capability: ClassVar[str] = "centrifuge"
    step_id: str
    targets: tuple[ResolvedContainerRef, ...]
    drive_value: float
    drive_unit: str
    duration_seconds: float
    method_profile: ProcessingMethodProfile | None = None
    program_kind: str | None = None


class ProcessingIntentPort(Protocol):
    def resolve_intent(self, pending: PendingEffect) -> ThermalHoldIntent | OrbitalShakeIntent | CentrifugeIntent | CentrifugeSeparationIntent | MagneticSeparationIntent: ...


@dataclass(frozen=True)
class MagneticSeparationIntent:
    capability: ClassVar[str] = "magnetic_separation"
    step_id: str
    targets: tuple[ResolvedContainerRef, ...]
    duration_seconds: float


@dataclass(frozen=True)
class MagneticReleaseIntent:
    step_id: str
    targets: tuple[ResolvedContainerRef, ...]
    producer_step_id: str


@dataclass(frozen=True)
class ProjectedConditionRelease:
    module_id: str
    labware: str
    source: str
    destination: str


class ProcessingIntentBindingPort(Protocol):
    def bind(self, intent, capability): ...
