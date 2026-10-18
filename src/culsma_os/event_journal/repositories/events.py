from dataclasses import asdict
import json
from typing import Protocol


class RunEventRepository(Protocol):

    def append_once(self, event): ...


class SqliteRunEventRepository:

    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_run_history(event_id TEXT PRIMARY KEY,record TEXT)"
            )

    def append_once(self, event):
        payload = json.dumps(asdict(event), sort_keys=True)
        with self.connection:
            old = self.connection.execute(
                "SELECT record FROM os_run_history WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if old and old[0] != payload:
                raise ValueError("RUN_EVENT_CONFLICT")
            self.connection.execute(
                "INSERT OR IGNORE INTO os_run_history VALUES(?,?)",
                (event.event_id, payload),
            )
