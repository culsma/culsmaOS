"""Authenticated HTTP over a local tunnel, or HTTPS through a trusted gateway."""
from http.client import HTTPConnection, HTTPSConnection, HTTPException
import json
from urllib.parse import urlsplit

from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import ConsoleReadError
from .http import READ_PATH
from .identity import TOKEN_PATTERN


class RemoteHTTPTransport:
    def __init__(self, endpoint, token_file):
        address = urlsplit(endpoint)
        if (address.scheme not in {'http', 'https'} or not address.hostname
                or address.username is not None or address.password is not None
                or address.path not in {'', '/'} or address.query or address.fragment
                or (address.scheme == 'http' and address.hostname not in {'127.0.0.1', '::1'})):
            raise ValueError('REMOTE_ENDPOINT_INVALID')
        self.address = address
        self.port = address.port
        self.token_file = token_file

    def read(self, request):
        try:
            token = self.token_file.read_text(encoding='ascii').strip()
        except (OSError, UnicodeError):
            raise ConsoleAccessError('REMOTE_CREDENTIAL_UNAVAILABLE') from None
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise ConsoleAccessError('REMOTE_CREDENTIAL_INVALID')
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        headers.update(self._gateway_headers())
        payload = {'station_id': request.station_id, 'operation': request.operation.value}
        if request.run_id is not None:
            payload['run_id'] = request.run_id
        connection_type = HTTPSConnection if self.address.scheme == 'https' else HTTPConnection
        connection = connection_type(self.address.hostname, self.port, timeout=40)
        try:
            connection.request('POST', READ_PATH, json.dumps(payload), headers)
            with connection.getresponse() as response:
                return self.read_response(response)
        except (HTTPException, OSError):
            raise OSError('REMOTE_CONNECTION_UNAVAILABLE') from None
        finally:
            connection.close()

    def _gateway_headers(self):
        return {}

    def read_response(self, response):
        # http.client does not follow redirects or use ambient proxy settings.
        if response.status == 401:
            raise ConsoleAccessError('REMOTE_CREDENTIAL_REJECTED')
        if response.status == 403:
            raise ConsoleAccessError('REMOTE_STATION_DENIED', 'forbidden')
        if response.status == 404:
            raise ConsoleReadError('REMOTE_RESOURCE_NOT_FOUND', 'not_found')
        if response.status != 200:
            raise ConsoleReadError('REMOTE_READ_FAILED', 'unavailable')
        limit = 8 * 1024 * 1024
        try:
            raw = response.read(limit + 1)
            if len(raw) <= limit:
                result = json.loads(raw)
                if isinstance(result, dict):
                    return result
        except (ValueError, RecursionError):
            pass
        raise ConsoleReadError('REMOTE_RESPONSE_INVALID', 'bad_response')
