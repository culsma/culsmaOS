"""Driver-owned station maintenance contracts; no vendor language or runtime assumptions."""
from typing import Literal, Protocol


class StationServicePort(Protocol):
    """OS journals identity and ownership; the driver validates device evidence.

    submit/inspect/cancel return a state from accepted, running, completed,
    rejected, unknown or cancelled. Only the driver can establish completion
    or safe release. Exceptions and uncertain outcomes do not authorize replay.
    describe returns driver-owned capabilities; OS forwards those details.
    """

    def describe(self) -> dict: ...
    def validate(self, identity: dict) -> None: ...
    def submit(self, request_id: str, identity: dict) -> dict: ...
    def inspect(self, request_id: str, identity: dict) -> dict: ...
    def cancel(self, request_id: str, identity: dict) -> dict: ...


class NativeMethodServicePort(StationServicePort, Protocol):
    """Optional driver extension for native packages and captured output.

    File transport is {path: relative name, data_base64: exact bytes}. The driver
    owns supported languages, file validation, dependencies, limits, preparation
    and execution. Preparation returns method_id, bundle_sha256 and mode without
    launching the method. OS treats the package and vendor output as opaque.

    logs returns base64 content, offset and next_offset (byte cursors). Content
    media types and text encodings belong to the driver capability description.
    No native method automatically updates experiment material accounting.
    """

    def prepare_native(self, entrypoint: str, files: list[dict[str, str]],
                       mode: Literal['simulation', 'physical']) -> dict: ...
    def logs(self, request_id: str, identity: dict, offset: int = 0,
             limit: int = 65536, stream: Literal['receipt', 'trace'] = 'receipt') -> dict: ...


class RunLogServicePort(Protocol):
    """Optional read-only output for an OS-owned attempt; never dispatches work."""
    def operation_logs(self, attempt_id: str, mode: str, description: dict,
                       offset: int = 0, limit: int = 65536, stream: str = 'receipt') -> dict: ...
