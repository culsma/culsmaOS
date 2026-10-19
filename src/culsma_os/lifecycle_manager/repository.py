"""Process ownership and durable host binding, with no device knowledge."""
from pathlib import Path
from typing import Protocol


class HostLeaseRepository(Protocol):
    def acquire(self) -> None: ...
    def close(self) -> None: ...


class ResidentConfigurationRepository(Protocol):
    def bind(self, fingerprint: str) -> None: ...
    def initialize_activation(self) -> None: ...
    def active(self) -> dict | None: ...
    def receipt(self, request_id=None) -> dict | None: ...
    def prepare(self, request_id, fingerprint, record) -> dict: ...
    def activate(self, request_id, record, expected_fingerprint) -> None: ...
    def settle(self, request_id, status, error=None) -> None: ...
    def interrupt_pending(self) -> None: ...
    def snapshot(self, directory, configuration) -> Path: ...


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

    def initialize_activation(self):
        with self.connection:
            self.connection.execute('CREATE TABLE IF NOT EXISTS os_configuration_activations(request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, error TEXT, record TEXT NOT NULL)')
            self.connection.execute('CREATE TABLE IF NOT EXISTS os_active_configuration(id INTEGER PRIMARY KEY CHECK(id=1),record TEXT NOT NULL)')

    def active(self):
        import json
        row = self.connection.execute('SELECT record FROM os_active_configuration WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def receipt(self, request_id=None):
        import json
        row = self.connection.execute('SELECT request_id,fingerprint,status,error,record FROM os_configuration_activations '+
            ('WHERE request_id=?' if request_id else 'ORDER BY rowid DESC LIMIT 1'), (request_id,) if request_id else ()).fetchone()
        if row is None:
            return None
        return {'request_id':row[0],'request_fingerprint':row[1],'status':row[2],'error':row[3],**json.loads(row[4])}

    def prepare(self, request_id, fingerprint, record):
        import json
        with self.connection:
            self.connection.execute('INSERT INTO os_configuration_activations VALUES(?,?,?,NULL,?)',
                                    (request_id,fingerprint,'accepted',json.dumps(record,sort_keys=True)))
        return self.receipt(request_id)

    def activate(self, request_id, record, expected_fingerprint):
        import json
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            current = self.connection.execute('SELECT fingerprint FROM os_resident_configuration WHERE id=1').fetchone()
            if current != (expected_fingerprint,):
                raise ValueError('HOST_CONFIGURATION_STALE')
            self.connection.execute('UPDATE os_resident_configuration SET fingerprint=? WHERE id=1',(record['fingerprint'],))
            self.connection.execute('INSERT OR REPLACE INTO os_active_configuration VALUES(1,?)',(json.dumps(record,sort_keys=True),))
            self.connection.execute("UPDATE os_configuration_activations SET status='starting' WHERE request_id=?",(request_id,))

    def settle(self, request_id, status, error=None):
        with self.connection:
            self.connection.execute('UPDATE os_configuration_activations SET status=?,error=? WHERE request_id=?',(status,error,request_id))

    def interrupt_pending(self):
        with self.connection:
            self.connection.execute("UPDATE os_configuration_activations SET status='interrupted',error='HOST_ACTIVATION_INTERRUPTED' WHERE status IN ('accepted','starting')")

    def snapshot(self, directory, configuration):
        import hashlib
        import json
        import os
        encoded = (json.dumps(configuration,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        directory = Path(directory);directory.mkdir(parents=True,exist_ok=True)
        path = directory/(hashlib.sha256(encoded).hexdigest()+'.json')
        try:
            descriptor = os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != encoded:
                raise ValueError('HOST_CONFIGURATION_SNAPSHOT_CHANGED')
        else:
            with os.fdopen(descriptor,'wb') as stream:
                stream.write(encoded);stream.flush();os.fsync(stream.fileno())
        return path

    def bind(self, fingerprint):
        with self.connection:
            current = self.connection.execute('SELECT fingerprint FROM os_resident_configuration WHERE id=1').fetchone()
            if current is not None and current[0] != fingerprint:
                raise ValueError('HOST_CONFIGURATION_MISMATCH')
            self.connection.execute('INSERT OR IGNORE INTO os_resident_configuration VALUES(1,?)', (fingerprint,))
