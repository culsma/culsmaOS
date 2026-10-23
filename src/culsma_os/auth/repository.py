from threading import Lock


class SessionCredentialRepository:
    """One process-local capability; no disk persistence or human identity claim."""
    def __init__(self):
        self.lock = Lock()
        self.digest = None
        self.automation_digest = None

    def store(self, digest):
        with self.lock:
            self.digest = digest

    def current(self):
        with self.lock:
            return self.digest

    def store_automation(self, digest):
        with self.lock:
            self.automation_digest = digest

    def current_automation(self):
        with self.lock:
            return self.automation_digest
