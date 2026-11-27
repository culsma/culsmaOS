"""Contracts for the first, read-only remote-access slice."""
from dataclasses import dataclass
from enum import Enum, StrEnum
import re


class RemoteConnectionMode(StrEnum):
    TUNNEL = 'tunnel'
    HTTPS = 'https'
    CLOUDFLARE = 'cloudflare'


class RemoteReadOperation(str, Enum):
    STATION = 'station'
    RUNS = 'runs'
    RUN = 'run'


@dataclass(frozen=True)
class RemoteAccessSettings:
    station_id: str
    enabled: bool = False

    def __post_init__(self):
        if (not isinstance(self.station_id, str)
                or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.station_id) is None
                or type(self.enabled) is not bool):
            raise ValueError('REMOTE_SETTINGS_INVALID')


@dataclass(frozen=True)
class RemoteReadRequest:
    station_id: str
    operation: RemoteReadOperation
    run_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.station_id, str) or not self.station_id:
            raise ValueError('REMOTE_STATION_REQUIRED')
        if not isinstance(self.operation, RemoteReadOperation):
            raise ValueError('REMOTE_READ_OPERATION_INVALID')
        if self.operation is RemoteReadOperation.RUN:
            if not isinstance(self.run_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.run_id) is None:
                raise ValueError('REMOTE_RUN_ID_INVALID')
        elif self.run_id is not None:
            raise ValueError('REMOTE_RUN_ID_UNEXPECTED')
