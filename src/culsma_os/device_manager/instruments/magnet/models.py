"""Device preparation inputs supplied after language and workspace resolution."""
from dataclasses import dataclass
from typing import Mapping, ClassVar
from culsma_os.workspace_manager.models import ResolvedContainerRef, LayoutSnapshot
from ..models import MethodResolutionRequest, ResolvedModuleMethod
from ..values import freeze_value


@dataclass(frozen=True)
class MagneticSeparationRequest:
    method: MethodResolutionRequest
    targets: tuple[ResolvedContainerRef, ...]
    duration_seconds: float
    layout: LayoutSnapshot


@dataclass(frozen=True)
class PreparedMagneticSeparation:
    request: MagneticSeparationRequest
    method: ResolvedModuleMethod
    driver_details: Mapping[str, object]

    def __post_init__(self):
        object.__setattr__(self, 'driver_details', freeze_value(self.driver_details))


@dataclass(frozen=True)
class MagneticSeparationIntent:
    capability: ClassVar[str] = "magnetic_separation"
    step_id: str
    targets: tuple[ResolvedContainerRef, ...]
    duration_seconds: float
