"""Driver-owned magnetic feasibility checks; preparation cannot dispatch."""
from typing import Protocol, Mapping
from .models import MagneticSeparationRequest
from ..models import ResolvedModuleMethod


class MagneticPreparationPort(Protocol):
    def prepare_magnetic_separation(self, request: MagneticSeparationRequest,
                                   method: ResolvedModuleMethod) -> Mapping[str, object]: ...
