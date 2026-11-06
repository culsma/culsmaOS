from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleState:
    ready: bool


from pathlib import Path
from culsma_os.program_manager.models import HostBuildContext


@dataclass(frozen=True)
class ResidentHostSettings:
    context: HostBuildContext
    socket_path: Path
    poll_interval: float = 0.05


@dataclass(frozen=True)
class ConsoleActivationRequest:
    action: str
    draft_id: str | None = None
    revision: int | None = None
    expected_fingerprint: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class WorkflowSimulationSettingRequest:
    enabled: bool
    revision: int


@dataclass(frozen=True)
class StationSelectionRequest:
    action: str
    profile_id: str | None = None
    expected_selected_profile: str | None = None


class StationSelectionError(ValueError):
    def __init__(self, code, kind='invalid_request'):
        super().__init__(code)
        self.code, self.kind = code, kind
