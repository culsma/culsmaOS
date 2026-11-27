"""Expose the normal MCP toolset through an authenticated loopback endpoint."""
from contextvars import ContextVar

from culsma_os.auth.models import ConsoleAccessError
from culsma_os.console.providers import ConsoleApplicationFactory
from ..models import RemoteAccessSettings
from .identity import FileRemoteIdentityAdapter


class RemoteConsoleHTTP:
    def __init__(self, settings, station_id, grants, *, is_enabled=None):
        RemoteAccessSettings(station_id)
        self.identity = FileRemoteIdentityAdapter(grants, station_id, scope='automation')
        self.is_enabled = is_enabled
        self.credential = ContextVar('remote_console_credential', default='')
        host = ConsoleApplicationFactory().build_mcp(settings, tokens=self)
        self.app = host.server.make_server('').streamable_http_app(
            stateless_http=True, json_response=True, host='127.0.0.1')

    def execute(self, _local_credential):
        """Verify the request's grant at the existing use-case boundary."""
        if self.is_enabled is not None and not self.is_enabled():
            raise ConsoleAccessError('REMOTE_ENDPOINT_DISABLED')
        return self.identity.execute(self.credential.get())

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        from starlette.responses import JSONResponse

        headers = [value for name, value in scope['headers'] if name == b'authorization']
        raw = headers[0].decode('latin-1') if len(headers) == 1 else ''
        reset = self.credential.set(raw)
        try:
            try:
                self.execute('')
            except ConsoleAccessError:
                await JSONResponse(
                    {'error': 'REMOTE_AUTOMATION_CREDENTIAL_REQUIRED'}, status_code=401,
                    headers={'Cache-Control': 'no-store', 'WWW-Authenticate': 'Bearer'},
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)
        finally:
            self.credential.reset(reset)

    def serve(self, port):
        import uvicorn

        uvicorn.run(self, host='127.0.0.1', port=port, lifespan='on',
                    proxy_headers=False, access_log=False)
