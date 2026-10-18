from typing import Protocol
from .models import OperationRequest


class OperationRepository(Protocol):

    def enqueue(self, request: OperationRequest) -> None: ...

    def set_status(self, effect_id: str, status: str) -> None: ...


class SqliteOperationRepository:

    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_operations(effect_id TEXT PRIMARY KEY,run_id TEXT,status TEXT)"
            )

    def enqueue(self, request):
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO os_operations VALUES(?,?,?)",
                (request.effect_id, request.run_id, request.status),
            )

    def set_status(self, effect_id, status):
        with self.connection:
            self.connection.execute(
                "UPDATE os_operations SET status=? WHERE effect_id=?",
                (status, effect_id),
            )
