"""Connection infrastructure only; repositories own their SQL and tables."""

from pathlib import Path
import sqlite3


class DatabaseConnection:

    def __init__(self, path: Path):
        self.path = path

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


class ReadOnlyDatabaseSnapshot:
    """Short-lived read transaction; missing stores and tables stay absent."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.connection = None
        self.tables = frozenset()
        self.active = False

    def __enter__(self):
        if self.active:
            raise RuntimeError("READ_SNAPSHOT_ALREADY_OPEN")
        self.active = True
        try:
            if self.path.exists():
                self.connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
                self.connection.execute("PRAGMA query_only=ON")
                self.connection.execute("BEGIN")
                self.tables = frozenset(row[0] for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def rows(self, table, statement, parameters=()):
        if not self.active:
            raise RuntimeError("READ_SNAPSHOT_NOT_OPEN")
        if table not in self.tables:
            return ()
        return tuple(self.connection.execute(statement, parameters))

    def __exit__(self, *args):
        try:
            if self.connection is not None:
                try:
                    self.connection.rollback()
                finally:
                    self.connection.close()
        finally:
            self.connection = None
            self.tables = frozenset()
            self.active = False
