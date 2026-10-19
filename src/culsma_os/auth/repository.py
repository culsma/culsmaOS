from threading import Lock


class SessionCredentialRepository:
    """One process-local capability; no disk persistence or human identity claim."""
    def __init__(self):
        self.lock = Lock()
        self.digest = None

    def store(self, digest):
        with self.lock:
            self.digest = digest

    def current(self):
        with self.lock:
            return self.digest
