"""Shared authorized use cases for console controls and external MCP tools."""
import re
from culsma_os.auth.interactors import AuthorizedInteractor
from ..models import SetupInteractionRequest, ConsoleProgramError, ConsoleReadRequest


class SetupInteractionInteractor(AuthorizedInteractor):
    required_capability = 'setup:operate'

    def __init__(self, tokens, resident):
        super().__init__(tokens)
        self.resident = resident

    def perform_authorized(self, caller, request):
        self.validate_request(request)
        payload = {'action': 'setup-' + request.action, 'run_id': request.run_id}
        if request.request_id is not None:
            payload['request_id'] = request.request_id
        if request.fingerprint is not None:
            payload['setup_fingerprint'] = request.fingerprint
        if request.preferences is not None:
            payload['setup_preferences'] = request.preferences
        if request.action == 'confirm':
            payload['setup_acknowledged'] = request.acknowledged
        payload['setup_origin'] = caller.subject
        try:
            return self.resident.execute(payload)
        except OSError as error:
            raise ConsoleProgramError('SETUP_HOST_UNAVAILABLE', 'unavailable') from error
        except ValueError as error:
            code = str(error)
            if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', code) is None:
                code = 'SETUP_HOST_REJECTED'
            raise ConsoleProgramError(code, 'conflict') from error

    def validate_request(self, request):
        if not isinstance(request, SetupInteractionRequest):
            raise ConsoleProgramError('SETUP_REQUEST_INVALID')
        required = {'show': (False, False), 'status': (True, False),
                    'begin': (True, True), 'revise': (True, True)}
        if request.action not in required:
            raise ConsoleProgramError('SETUP_ACTION_UNSUPPORTED')
        self.validate_fields(request, *required[request.action])
        if (request.acknowledged is not False
                or request.preferences is not None and request.action != 'revise'
                or request.action == 'revise' and not isinstance(request.preferences, dict)):
            raise ConsoleProgramError('SETUP_REQUEST_INVALID')

    def validate_fields(self, request, request_id, fingerprint):
        if (not isinstance(request.run_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request.run_id) is None
                or request_id != (request.request_id is not None)
                or request.request_id is not None and (not isinstance(request.request_id, str)
                    or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request.request_id) is None)
                or fingerprint != (request.fingerprint is not None)
                or request.fingerprint is not None and (not isinstance(request.fingerprint, str)
                    or re.fullmatch(r'[a-f0-9]{64}', request.fingerprint) is None)):
            raise ConsoleProgramError('SETUP_REQUEST_INVALID')


class SetupConfirmationInteractor(SetupInteractionInteractor):
    required_capability = 'setup:confirm'

    def validate_request(self, request):
        if (not isinstance(request, SetupInteractionRequest) or request.action != 'confirm'
                or request.acknowledged is not True or request.preferences is not None):
            raise ConsoleProgramError('SETUP_EXPLICIT_CONFIRMATION_REQUIRED')
        self.validate_fields(request, True, True)


class AutomationObservationInteractor(AuthorizedInteractor):
    required_capability = 'setup:operate'

    def __init__(self, tokens, observation):
        super().__init__(tokens)
        self.observation = observation

    def perform(self, request):
        if not isinstance(request, ConsoleReadRequest):
            raise ConsoleProgramError('SETUP_REQUEST_INVALID')
        return self.observation.execute(request).as_dict()
