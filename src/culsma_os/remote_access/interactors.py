"""Remote admission reuses the OS authorization base and console read use case."""
import logging

from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import ConsoleReadRequest
from .models import RemoteAccessSettings, RemoteReadRequest
from .ports import RemoteIdentityPort


class RemoteReadInteractor(AuthorizedInteractor):
    required_capability = 'station:read'

    def __init__(self, settings: RemoteAccessSettings, identity: RemoteIdentityPort, observation):
        super().__init__(identity)
        self.settings, self.observation = settings, observation

    def perform_authorized(self, caller, request):
        if not self.settings.enabled:
            raise ConsoleAccessError('REMOTE_ACCESS_DISABLED', 'forbidden')
        if not isinstance(request, RemoteReadRequest):
            raise ValueError('REMOTE_READ_REQUEST_INVALID')
        if (request.station_id != self.settings.station_id
                or f'station:{self.settings.station_id}:read' not in caller.capabilities):
            raise ConsoleAccessError('REMOTE_STATION_DENIED', 'forbidden')
        try:
            return self.observation.execute(
                ConsoleReadRequest(request.operation.value, request.run_id)).as_dict()
        finally:
            logging.getLogger(__name__).info('Remote read: subject=%s station=%s operation=%s',
                caller.subject, self.settings.station_id, request.operation.value)
