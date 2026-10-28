"""Console presentation records, never experiment or physical observations."""
from dataclasses import dataclass


class ViewInteractionError(ValueError):
    def __init__(self, code, kind='invalid_request'):
        super().__init__(code)
        self.code, self.kind = code, kind


@dataclass(frozen=True)
class RendererSession:
    session_id: str
    epoch: str
    revision: int
    last_seen: float
    state: dict


@dataclass(frozen=True)
class ViewStateReadRequest:
    action: str = 'sessions'
    request_id: str | None = None


@dataclass(frozen=True)
class ViewRequest:
    action: str
    request_id: str
    session_id: str
    epoch: str
    expected_revision: int
    view: str
    entity_id: str | None = None


@dataclass(frozen=True)
class RendererSessionRequest:
    action: str
    session_id: str | None = None
    epoch: str | None = None
    revision: int | None = None
    state: dict | None = None
    request_id: str | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class ViewReceipt:
    request_id: str
    status: str
    session_id: str
    epoch: str
    outcome: str | None = None
