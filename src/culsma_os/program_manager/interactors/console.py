"""Read-only console use cases over the existing resident command boundary."""
from datetime import datetime, timezone
import re

from ..models import ConsoleReadError, ConsoleReadRequest, ConsoleReadResponse, ResidentReadPort


class ConsoleCommandInteractor:
    def __init__(self, resident: ResidentReadPort):
        self.resident = resident

    def execute(self, request: ConsoleReadRequest) -> ConsoleReadResponse:
        if not isinstance(request, ConsoleReadRequest) or not isinstance(request.resource, str):
            raise ConsoleReadError("CONSOLE_REQUEST_INVALID", "invalid_request")
        if request.resource not in {"station", "runs", "run"}:
            raise ConsoleReadError("CONSOLE_READ_ONLY", "read_only")
        if request.resource == "run":
            self.validate_run_id(request.run_id)
            data = self.read({"action": "status", "run_id": request.run_id})
            try:
                data['execution_evidence'] = self.read({'action': 'run-evidence', 'run_id': request.run_id})
            except ConsoleReadError as error:
                if error.code != 'HOST_COMMAND_UNSUPPORTED':
                    raise
                data['execution_evidence'] = None
        else:
            if request.run_id is not None:
                raise ConsoleReadError("CONSOLE_REQUEST_INVALID", "invalid_request")
            if request.resource == "station":
                data = {"host": self.read({"action": "host-status"}),
                        "devices": self.read({"action": "device-status"}),
                        "runs": self.read({"action": "runs"})["runs"]}
            else:
                data = self.read({"action": "runs"})
        return ConsoleReadResponse(request.resource, datetime.now(timezone.utc).isoformat(), data)

    def validate_run_id(self, run_id):
        if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id) is None:
            raise ConsoleReadError("CONSOLE_RUN_ID_INVALID", "invalid_request")

    def read(self, payload):
        if (not isinstance(payload, dict) or set(payload) - {"action", "run_id"}
                or not isinstance(payload.get("action"), str)
                or payload.get("action") not in {"host-status", "device-status", "runs", "status", "run-evidence"}):
            raise ConsoleReadError("CONSOLE_READ_ONLY", "read_only")
        if payload["action"] in {"status", "run-evidence"}:
            self.validate_run_id(payload.get("run_id"))
        elif "run_id" in payload:
            raise ConsoleReadError("CONSOLE_REQUEST_INVALID", "invalid_request")
        try:
            result = self.resident.execute(payload)
        except OSError as error:
            raise ConsoleReadError("CONSOLE_HOST_UNAVAILABLE", "unavailable") from error
        except ValueError as error:
            code = str(error)
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) is None:
                code = "CONSOLE_BACKEND_REJECTED"
            raise ConsoleReadError(code, "not_found" if code == "HOST_RUN_NOT_FOUND" else "bad_response") from error
        if not isinstance(result, dict) or (payload["action"] == "runs"
                and not isinstance(result.get("runs"), list)):
            raise ConsoleReadError("CONSOLE_BACKEND_RESPONSE_INVALID", "bad_response")
        return result
