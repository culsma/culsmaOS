import hashlib
import hmac
import secrets
from threading import Lock
from .models import CallerContext, ConsoleAccessError


class TokenInteractor:
    def __init__(self, repository):
        self.repository = repository
        self.token = None
        self.lock = Lock()

    def issue_console_session(self):
        with self.lock:
            if self.token is None:
                self.token = secrets.token_urlsafe(32)
                self.repository.store(hashlib.sha256(self.token.encode()).hexdigest())
            return self.token

    def execute(self, raw_credential):
        if (not isinstance(raw_credential,str) or not raw_credential.startswith('Bearer ')
                or len(raw_credential) > 256):
            raise ConsoleAccessError('CONSOLE_SESSION_REQUIRED')
        digest = hashlib.sha256(raw_credential[7:].encode()).hexdigest()
        current = self.repository.current()
        if current is None or not hmac.compare_digest(current,digest):
            raise ConsoleAccessError('CONSOLE_SESSION_INVALID')
        return CallerContext('local-console-process',frozenset({'configuration:drafts','configuration:activate','programs:execute'}))


class AuthorizedInteractor:
    required_capability = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if 'execute' in cls.__dict__ or not cls.required_capability:
            raise TypeError('Protected use cases must use the fixed authorized entry')

    def __init__(self, tokens):
        self.tokens = tokens

    def execute(self, raw_credential, request):
        caller = self.tokens.execute(raw_credential)
        if self.required_capability not in caller.capabilities:
            raise ConsoleAccessError('CONSOLE_CAPABILITY_DENIED','forbidden')
        return self.perform(request)
