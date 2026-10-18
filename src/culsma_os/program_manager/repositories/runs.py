from dataclasses import replace
from typing import Protocol
from ..models import RunRecord, RunConflict, RunStateEvent


class TaskRepository(Protocol):

    def save(self, record: RunRecord, *, queue_submission=None) -> RunRecord: ...

    def get(self, run_id: str) -> RunRecord: ...

    def unfinished(self) -> tuple[RunRecord, ...]: ...

    def pending_events(self) -> tuple[RunStateEvent, ...]: ...

    def mark_published(self, event_id: str) -> None: ...


class SqliteTaskRepository:

    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_runs (run_id TEXT PRIMARY KEY,status TEXT,checkpoint TEXT,revision INTEGER,error TEXT)"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(os_runs)")}
            if "body_outcome" not in columns:
                connection.execute("ALTER TABLE os_runs ADD COLUMN body_outcome TEXT")
            if "body_error" not in columns:
                connection.execute("ALTER TABLE os_runs ADD COLUMN body_error TEXT")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_run_outbox(event_id TEXT PRIMARY KEY,run_id TEXT,status TEXT,revision INTEGER,published INTEGER DEFAULT 0)"
            )

    def save(self, record, *, queue_submission=None):
        with self.connection:
            row = self.connection.execute(
                "SELECT revision FROM os_runs WHERE run_id=?", (record.run_id,)
            ).fetchone()
            if row is None:
                if record.revision != 0:
                    raise RunConflict("RUN_REVISION_CONFLICT")
                self.connection.execute(
                    "INSERT INTO os_runs(run_id,status,checkpoint,revision,error,body_outcome,body_error) VALUES (?,?,?,?,?,?,?)",
                    (record.run_id, record.status, record.checkpoint, 1, record.error, record.body_outcome, record.body_error),
                )
                self.connection.execute(
                    "INSERT INTO os_run_outbox(event_id,run_id,status,revision) VALUES(?,?,?,?)",
                    (f"{record.run_id}:1", record.run_id, record.status, 1),
                )
                if queue_submission is not None:
                    self.connection.execute(
                        "INSERT INTO os_run_queue(run_id,source,request_id,fingerprint) VALUES(?,?,?,?)",
                        (record.run_id, queue_submission.source, queue_submission.request_id, queue_submission.fingerprint))
                return replace(record, revision=1)
            changed = self.connection.execute(
                "UPDATE os_runs SET status=?,checkpoint=?,revision=revision+1,error=?,body_outcome=?,body_error=? WHERE run_id=? AND revision=?",
                (
                    record.status,
                    record.checkpoint,
                    record.error,
                    record.body_outcome,
                    record.body_error,
                    record.run_id,
                    record.revision,
                ),
            ).rowcount
            if changed != 1:
                raise RunConflict("RUN_REVISION_CONFLICT")
            self.connection.execute(
                "INSERT INTO os_run_outbox(event_id,run_id,status,revision) VALUES(?,?,?,?)",
                (
                    f"{record.run_id}:{record.revision + 1}",
                    record.run_id,
                    record.status,
                    record.revision + 1,
                ),
            )
            return replace(record, revision=record.revision + 1)

    def get(self, run_id):
        row = self.connection.execute(
            "SELECT run_id,status,checkpoint,revision,error,body_outcome,body_error FROM os_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunRecord(*row)

    def unfinished(self):
        return tuple(
            (
                RunRecord(*row)
                for row in self.connection.execute(
                    "SELECT run_id,status,checkpoint,revision,error,body_outcome,body_error FROM os_runs WHERE status NOT IN ('completed','failed','cancelled') OR body_outcome IS NULL"
                )
            )
        )

    def pending_events(self):
        return tuple(
            (
                RunStateEvent(*row)
                for row in self.connection.execute(
                    "SELECT event_id,run_id,status,revision FROM os_run_outbox WHERE published=0 ORDER BY revision"
                )
            )
        )

    def mark_published(self, event_id):
        with self.connection:
            self.connection.execute(
                "UPDATE os_run_outbox SET published=1 WHERE event_id=?", (event_id,)
            )
