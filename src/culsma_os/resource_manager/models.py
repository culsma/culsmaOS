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
