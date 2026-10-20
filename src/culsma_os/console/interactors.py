"""Local desktop lifecycle; execution and resource ownership stay in the resident."""
import threading
import time
from culsma_os.program_manager.models import ConsoleReadError, ConsoleReadRequest
from .models import NativeApplicationPort, LocalResidentStartupPort


class DesktopConsoleInteractor:
    def __init__(self, server, sessions, application: NativeApplicationPort,
                 resident: LocalResidentStartupPort | None = None, timeout=30):
        self.server, self.sessions = server, sessions
        self.application, self.resident, self.timeout = application, resident, timeout

    def wait_ready(self):
        deadline = time.monotonic() + self.timeout
        started = False
        while True:
            try:
                snapshot = self.server.commands.execute(ConsoleReadRequest('station'))
                status = snapshot.data['host']['status']
                if status == 'ready':
                    return
                if status in {'failed', 'stopped'}:
                    raise ValueError('DESKTOP_STATION_NOT_READY')
            except ConsoleReadError as error:
                if error.code != 'CONSOLE_HOST_UNAVAILABLE':
                    raise
                if not started:
                    if self.resident is None:
                        raise ValueError('DESKTOP_RESIDENT_REQUIRED') from None
                    self.resident.start()
                    started = True
            if time.monotonic() >= deadline:
                raise ValueError('DESKTOP_STARTUP_TIMEOUT')
            time.sleep(0.1)

    def execute(self):
        try:
            self.wait_ready()
            thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            thread.start()
            try:
                session = self.sessions.execute()
                # Capability remains private to the child pipe; no new public bootstrap endpoint.
                return self.application.run({'schema': 'culsma_desktop_v1', 'origin': self.server.url,
                                             'access_token': session['access_token']})
            finally:
                self.server.shutdown()
                thread.join(timeout=5)
        finally:
            self.server.server_close()
        # The resident outlives this UI. Closing a window is not a station shutdown command.
