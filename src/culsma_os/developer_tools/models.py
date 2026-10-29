from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FaultTestRequest:
    scenario: str


class FaultTestPort(Protocol):
    def execute(self, scenario: str) -> dict: ...
