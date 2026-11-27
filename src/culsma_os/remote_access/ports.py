"""Remote identity verification and transport contracts."""
from typing import Protocol
from culsma_os.auth.models import CallerContext
from .models import RemoteReadRequest


class RemoteIdentityPort(Protocol):
    def execute(self, raw_credential: str) -> CallerContext:
        """Verify credential, expiry, revocation and station grants per request.

        Return the verified subject and effective capabilities, including a
        station:<id>:read grant when authorized. No shared local-console token.
        """
        ...


class RemoteReadTransportPort(Protocol):
    def read(self, request: RemoteReadRequest) -> dict:
        """Send a station read over an authenticated connection."""
        ...
