from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPermit:
    effect_id: str
    attempt_id: str
    resources: tuple[str, ...]
    run_reservation: "RunReservation | None" = None


class ResourceConflict(ValueError):
    pass


@dataclass(frozen=True)
class RunReservation:
    station_id: str
    run_id: str
    owner_id: str
    generation: int
    run_store: str
    resources: tuple[str, ...]
    status: str = "active"


@dataclass(frozen=True)
class RunReleaseConfirmation:
    run_id: str
    run_store: str
    generation: int
    revision: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SupplyReplacementRequest:
    action: str = 'show'
    request_id: str | None = None
    expected_revision: str | None = None
    resource_id: str | None = None
    positions: list[str] | None = None
    simulation_acknowledged: bool = False


class SupplyReplacementError(ValueError):
    def __init__(self, code, kind='conflict'):
        super().__init__(code)
        self.code, self.kind = code, kind


from typing import Protocol


class SupplyReplacementPort(Protocol):
    """Optional driver-owned simulation stock boundary; no vendor types cross it."""
    def describe(self) -> dict: ...
    def replace(self, request_id: str, expected_revision: str, positions: list[str]) -> dict: ...
    def receipt(self, request_id: str, token: str, resource: str) -> dict | None: ...
