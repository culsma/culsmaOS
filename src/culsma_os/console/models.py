"""Immutable local HTTP transport settings."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class NativeApplicationPort(Protocol):
    def run(self, connection: dict) -> int: ...


class LocalResidentStartupPort(Protocol):
    def start(self) -> None: ...


@dataclass(frozen=True)
class ConsoleSettings:
    socket_path: Path
    port: int = 8765
    drafts_path: Path | None = None
    program_root: Path | None = None
    program_store: Path | None = None

    def __post_init__(self):
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ValueError("CONSOLE_PORT_INVALID")
