"""HTTPS transport through a Cloudflare Access application."""
import json
import re

from culsma_os.auth.models import ConsoleAccessError
from .transport import RemoteHTTPTransport


class CloudflareAccessTransport(RemoteHTTPTransport):
    def __init__(self, endpoint, token_file, access_token_file):
        super().__init__(endpoint, token_file)
        if self.address.scheme != 'https':
            raise ValueError('REMOTE_ACCESS_REQUIRES_HTTPS')
        self.access_token_file = access_token_file

    def _gateway_headers(self):
        try:
            with self.access_token_file.open(encoding='ascii') as source:
                raw = source.read(4097)
        except OSError:
            raise ConsoleAccessError('REMOTE_ACCESS_CREDENTIAL_UNAVAILABLE') from None
        except UnicodeError:
            raise ConsoleAccessError('REMOTE_ACCESS_CREDENTIAL_INVALID') from None
        try:
            credentials = json.loads(raw) if len(raw) <= 4096 else None
        except (ValueError, RecursionError):
            raise ConsoleAccessError('REMOTE_ACCESS_CREDENTIAL_INVALID') from None
        if not isinstance(credentials, dict):
            raise ConsoleAccessError('REMOTE_ACCESS_CREDENTIAL_INVALID')
        headers = {}
        for field, header in (('client_id', 'CF-Access-Client-Id'),
                              ('client_secret', 'CF-Access-Client-Secret')):
            value = credentials.get(field)
            if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9._-]{1,512}', value) is None:
                raise ConsoleAccessError('REMOTE_ACCESS_CREDENTIAL_INVALID')
            headers[header] = value
        return headers
