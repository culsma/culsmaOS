"""Authorized console access to the resident's existing device service."""
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.program_manager.models import ConsoleReadError


class ConsoleStationServiceInteractor(AuthorizedInteractor):
    required_capability = 'programs:execute'

    def __init__(self, tokens, resident):
        super().__init__(tokens)
        self.resident = resident

    def perform_authorized(self, caller, request):
        from culsma_os.auth.models import ConsoleAccessError
        if (isinstance(request, dict) and request.get('action') in {'set-physical-permission', 'set-native-debug'}
                and 'configuration:activate' not in caller.capabilities):
            raise ConsoleAccessError('CONSOLE_CAPABILITY_DENIED', 'forbidden')
        return self.perform(request)

    def perform(self, request):
        if not isinstance(request, dict) or request.get('action') not in {
                'describe', 'initialize', 'status', 'cancel', 'physical-permission-status', 'set-physical-permission',
                'set-native-debug', 'prepare-native', 'execute-native', 'native-logs', 'run-logs'}:
            raise ConsoleReadError('STATION_SERVICE_REQUEST_INVALID', 'invalid_request')
        try:
            return self.resident.execute({
                'action': 'station-service', 'station_service_request': request})
        except OSError as error:
            # The request may already have reached the resident. Reconcile its ID.
            raise ConsoleReadError('STATION_SERVICE_CONNECTION_LOST', 'unavailable') from error
        except ValueError as error:
            raise ConsoleReadError(str(error), 'conflict') from error
