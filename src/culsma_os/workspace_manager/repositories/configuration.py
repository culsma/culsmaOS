"""Append-only draft revisions in a store separate from station/run records."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Protocol
from ..models import ConfigurationError, StationConfigurationDraft


class StationConfigurationRepository(Protocol):
    def list(self) -> list[StationConfigurationDraft]: ...
    def get(self, draft_id, revision=None) -> StationConfigurationDraft: ...
    def save(self, draft_id, expected_revision, value) -> StationConfigurationDraft: ...


class SqliteStationConfigurationRepository:
    def __init__(self, path):
        self.path = Path(path)

    def list(self):
        if not self.path.is_file():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
            rows = connection.execute('SELECT record FROM configuration_drafts d WHERE revision=(SELECT max(revision) FROM configuration_drafts WHERE draft_id=d.draft_id) ORDER BY draft_id')
            return [StationConfigurationDraft.from_record(json.loads(row[0])) for row in rows]

    def get(self, draft_id, revision=None):
        if not self.path.is_file():
            raise ConfigurationError('CONFIGURATION_DRAFT_NOT_FOUND','not_found')
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
            if revision is None:
                row = connection.execute('SELECT record FROM configuration_drafts WHERE draft_id=? ORDER BY revision DESC LIMIT 1',(draft_id,)).fetchone()
            else:
                row = connection.execute('SELECT record FROM configuration_drafts WHERE draft_id=? AND revision=?',(draft_id,revision)).fetchone()
        if row is None:
            raise ConfigurationError('CONFIGURATION_DRAFT_NOT_FOUND','not_found')
        return StationConfigurationDraft.from_record(json.loads(row[0]))

    def save(self, draft_id, expected_revision, value):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path,timeout=5)) as connection, connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE IF NOT EXISTS configuration_drafts(draft_id TEXT,revision INTEGER,record TEXT,PRIMARY KEY(draft_id,revision))')
            current = connection.execute('SELECT max(revision) FROM configuration_drafts WHERE draft_id=?',(draft_id,)).fetchone()[0] or 0
            if current != expected_revision:
                raise ConfigurationError('CONFIGURATION_REVISION_CONFLICT','conflict')
            record = {**value,'draft_id':draft_id,'revision':current+1}
            connection.execute('INSERT INTO configuration_drafts VALUES(?,?,?)',(draft_id,current+1,json.dumps(record,allow_nan=False)))
        return StationConfigurationDraft.from_record(record)
