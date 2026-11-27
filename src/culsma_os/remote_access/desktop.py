"""Manage the remote endpoint from the authenticated native station console."""
from dataclasses import replace
import socket
from threading import Event, Lock, Thread
from time import monotonic, sleep

from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.auth.models import ConsoleAccessError

from .adapters.console_http import RemoteConsoleHTTP
from .adapters.identity import FileRemoteIdentityAdapter


class DesktopRemoteAccess(AuthorizedInteractor):
    required_capability = 'remote:manage'

    def __init__(self, tokens, settings, station_id, grants, port=8768):
        super().__init__(tokens)
        self.settings = replace(settings, port=port)
        self.identity = FileRemoteIdentityAdapter(grants, station_id, scope='automation')
        self.preference = grants / 'enabled'
        self.lock = Lock()
        self.enabled = Event()
        self.server = None
        self.thread = None

    def perform(self, request):
        if not isinstance(request, dict):
            raise ConsoleAccessError('REMOTE_REQUEST_INVALID', 'invalid_request')
        action = request.get('action')
        with self.lock:
            try:
                token = None
                if action == 'enable':
                    self._enable()
                    try:
                        self.preference.parent.mkdir(parents=True, exist_ok=True)
                        self.preference.touch()
                    except OSError:
                        self._disable()
                        raise
                elif action == 'disable':
                    self.preference.unlink(missing_ok=True)
                    self._disable()
                elif action == 'pair':
                    token = self.identity.pair(request.get('name'))
                elif action == 'unpair':
                    self.identity.unpair(request.get('id'))
                elif action != 'status':
                    raise ValueError('REMOTE_REQUEST_INVALID')
                result = {
                    'enabled': self.enabled.is_set() and self.thread.is_alive(),
                    'port': self.settings.port,
                    'pairings': self.identity.pairings(),
                }
                if token is not None:
                    result['token'] = token
                return result
            except ValueError as error:
                raise ConsoleAccessError(str(error), 'invalid_request') from None
            except (OSError, ImportError) as error:
                code = 'REMOTE_PORT_UNAVAILABLE' if action == 'enable' else 'REMOTE_PAIRING_STORAGE_UNAVAILABLE'
                raise ConsoleAccessError(code, 'unavailable') from error

    def _enable(self):
        import uvicorn

        if self.thread is not None and self.thread.is_alive():
            if self.enabled.is_set():
                return
            raise ConsoleAccessError('REMOTE_ENDPOINT_STOPPING', 'conflict')
        self.enabled.clear()
        app = RemoteConsoleHTTP(self.settings, self.identity.station_id,
                                self.identity.grants, is_enabled=self.enabled.is_set)
        server = uvicorn.Server(uvicorn.Config(
            app, host='127.0.0.1', port=self.settings.port, lifespan='on',
            proxy_headers=False, access_log=False, timeout_graceful_shutdown=3,
        ))
        listener = socket.socket()
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', self.settings.port))
            thread = Thread(target=self._serve, args=(server, listener), daemon=True)
            thread.start()
        except BaseException:
            listener.close()
            raise
        self.server, self.thread = server, thread
        deadline = monotonic() + 5
        while thread.is_alive() and not server.started and monotonic() < deadline:
            sleep(0.02)
        if not server.started or not thread.is_alive():
            self._disable()
            raise ConsoleAccessError('REMOTE_ENDPOINT_START_FAILED', 'unavailable')
        self.enabled.set()

    @staticmethod
    def _serve(server, listener):
        with listener:
            server.run(sockets=[listener])

    def _disable(self):
        self.enabled.clear()
        if self.thread is not None:
            self.server.should_exit = True
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise ConsoleAccessError('REMOTE_ENDPOINT_STOPPING', 'unavailable')
            self.server = self.thread = None

    def restore(self):
        with self.lock:
            if self.preference.is_file():
                try:
                    self._enable()
                except (OSError, ImportError) as error:
                    raise ValueError('REMOTE_PORT_UNAVAILABLE') from error

    def close(self):
        with self.lock:
            self._disable()
