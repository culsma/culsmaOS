"""Immutable local HTTP transport settings."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConsoleSettings:
    socket_path: Path
    port: int = 8765
    drafts_path: Path | None = None

    def __post_init__(self):
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ValueError("CONSOLE_PORT_INVALID")
