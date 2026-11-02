"""Static profile management contracts; no run binding or device commands."""
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class InstrumentProfileRequest:
    action: str
    device_id: str
    module_id: str | None = None
    draft_id: str | None = None
    configuration_revision: int | None = None
    profile_id: str | None = None
    profile_revision: str | None = None
    expected_revision: str | None = None
    method_id: str | None = None
    definition_revision: str | None = None
    display_name: str | None = None
    parameters: Mapping[str, object] | None = None
    applicability: dict | None = None
