"""Process ownership and durable host binding, with no device knowledge."""
from pathlib import Path
from typing import Protocol


class HostLeaseRepository(Protocol):
    def acquire(self) -> None: ...
    def close(self) -> None: ...


class ResidentConfigurationRepository(Protocol):
    def bind(self, fingerprint: str) -> None: ...


class LocalHostLeaseRepository:
    def __init__(self, paths):
        self.paths = tuple(sorted(set(Path(p).resolve() for p in paths)))
        self.handles = []

    def acquire(self):
        try:
            import fcntl
        except ImportError as error:
            raise ValueError('HOST_POSIX_REQUIRED') from error
        if self.handles:
            raise ValueError('HOST_LEASE_ALREADY_ACQUIRED')
        try:
            for path in self.paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                handle = path.open('a+')
                self.handles.append(handle)
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ValueError('HOST_ALREADY_RUNNING') from error
        except BaseException:
            self.close()
            raise

    def close(self):
        for handle in reversed(self.handles):
            handle.close()
        self.handles.clear()


class SqliteResidentConfigurationRepository:
    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute('CREATE TABLE IF NOT EXISTS os_resident_configuration(id INTEGER PRIMARY KEY CHECK(id=1), fingerprint TEXT NOT NULL)')

    def bind(self, fingerprint):
        with self.connection:
            current = self.connection.execute('SELECT fingerprint FROM os_resident_configuration WHERE id=1').fetchone()
            if current is not None and current[0] != fingerprint:
                raise ValueError('HOST_CONFIGURATION_MISMATCH')
            self.connection.execute('INSERT OR IGNORE INTO os_resident_configuration VALUES(1,?)', (fingerprint,))
