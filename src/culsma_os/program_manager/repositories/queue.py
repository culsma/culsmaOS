"""Durable ordering and control inbox; execution state stays in RunStateInteractor."""
from typing import Protocol
from ..models import QueuedRun


class RunQueueRepository(Protocol):
    def entries(self) -> tuple[QueuedRun, ...]: ...
    def submission(self, request_id) -> QueuedRun | None: ...
    def head(self) -> QueuedRun | None: ...
    def contains(self, run_id) -> bool: ...
    def add_control(self, request_id, run_id, action) -> dict: ...
    def control(self, request_id) -> dict: ...
    def pending_controls(self, run_id=None) -> tuple[dict, ...]: ...
    def settle_control(self, request_id, error=None) -> None: ...


class SqliteRunQueueRepository:
    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS os_run_queue(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES os_runs(run_id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS os_run_commands(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL,
                run_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                FOREIGN KEY(run_id) REFERENCES os_runs(run_id))""")

    def entries(self):
        return tuple(QueuedRun(*row) for row in self.connection.execute(
            "SELECT sequence,run_id,source,request_id,fingerprint FROM os_run_queue ORDER BY sequence"))

    def submission(self, request_id):
        row = self.connection.execute(
            "SELECT sequence,run_id,source,request_id,fingerprint FROM os_run_queue WHERE request_id=?",
            (request_id,)).fetchone()
        return QueuedRun(*row) if row else None

    def head(self):
        row = self.connection.execute("""SELECT q.sequence,q.run_id,q.source,q.request_id,q.fingerprint
            FROM os_run_queue q JOIN os_runs r ON q.run_id=r.run_id
            WHERE r.status NOT IN ('completed','failed','cancelled') OR r.body_outcome IS NULL
            ORDER BY q.sequence LIMIT 1""").fetchone()
        return QueuedRun(*row) if row else None

    def contains(self, run_id):
        return self.connection.execute("SELECT 1 FROM os_run_queue WHERE run_id=?", (run_id,)).fetchone() is not None

    def add_control(self, request_id, run_id, action):
        with self.connection:
            row = self.connection.execute(
                "SELECT run_id,action FROM os_run_commands WHERE request_id=?", (request_id,)).fetchone()
            if row is not None and row != (run_id, action):
                raise ValueError("HOST_CONTROL_ID_CONFLICT")
            self.connection.execute(
                "INSERT OR IGNORE INTO os_run_commands(request_id,run_id,action) VALUES(?,?,?)",
                (request_id, run_id, action))
        return self.control(request_id)

    def control(self, request_id):
        row = self.connection.execute(
            "SELECT request_id,run_id,action,status,error FROM os_run_commands WHERE request_id=?",
            (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        return dict(zip(('request_id','run_id','action','status','error'), row))

    def pending_controls(self, run_id=None):
        rows = self.connection.execute(
            "SELECT request_id FROM os_run_commands WHERE status='pending' " +
            ("AND run_id=? " if run_id else "") + "ORDER BY sequence LIMIT 100",
            (run_id,) if run_id else ())
        return tuple(self.control(row[0]) for row in rows)

    def settle_control(self, request_id, error=None):
        with self.connection:
            self.connection.execute("UPDATE os_run_commands SET status=?,error=? WHERE request_id=? AND status='pending'",
                                    ('rejected' if error else 'applied', error, request_id))
