import hashlib
import hmac
import secrets
from threading import Lock
from .models import CallerContext, ConsoleAccessError


class TokenInteractor:
    def __init__(self, repository):
        self.repository = repository
        self.token = None
        self.automation_token = None
        self.lock = Lock()

    def issue_console_session(self):
        with self.lock:
            if self.token is None:
                self.token = secrets.token_urlsafe(32)
                self.repository.store(hashlib.sha256(self.token.encode()).hexdigest())
            return self.token

    def issue_automation_session(self):
        with self.lock:
            if self.automation_token is None:
                self.automation_token = secrets.token_urlsafe(32)
                self.repository.store_automation(hashlib.sha256(self.automation_token.encode()).hexdigest())
            return self.automation_token

    def execute(self, raw_credential):
        if (not isinstance(raw_credential,str) or not raw_credential.startswith('Bearer ')
                or len(raw_credential) > 256):
            raise ConsoleAccessError('CONSOLE_SESSION_REQUIRED')
        digest = hashlib.sha256(raw_credential[7:].encode()).hexdigest()
        current = self.repository.current()
        if current is not None and hmac.compare_digest(current, digest):
            return CallerContext('local-console-process', frozenset({'configuration:drafts','configuration:activate',
                'programs:execute','setup:operate','setup:confirm'}))
        automation = self.repository.current_automation()
        if automation is not None and hmac.compare_digest(automation, digest):
            return CallerContext('local-mcp-process', frozenset({'programs:execute','setup:operate'}))
        raise ConsoleAccessError('CONSOLE_SESSION_INVALID')


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
        return self.perform_authorized(caller, request)

    def perform_authorized(self, caller, request):
        return self.perform(request)
