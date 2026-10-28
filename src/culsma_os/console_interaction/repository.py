"""Station-local presentation persistence and atomic compare-and-swap operations."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Protocol
import uuid
from .models import ViewInteractionError


class ViewInteractionRepository(Protocol):
    def create_session(self, owner, now, state): ...
    def session(self, session_id): ...
    def sessions(self): ...
    def publish(self, session_id, epoch, owner, revision, now, state, closed=False): ...
    def enqueue(self, payload, now, lease, lifetime): ...
    def receipt(self, request_id): ...
    def pending(self, session_id, epoch): ...
    def acknowledge(self, session_id, epoch, owner, revision, request_id, outcome, state, now): ...


class SqliteViewInteractionRepository:
    def __init__(self, path, station_id):
        self.path, self.station_id = Path(path), station_id
        if self.path.is_symlink():
            raise ValueError('CONSOLE_VIEW_STORE_SYMLINK')
        if self.path.exists():
            with self.connection():
                pass

    def initialize_schema(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS console_view_station (station_id TEXT PRIMARY KEY)')
        saved = db.execute('SELECT station_id FROM console_view_station').fetchone()
        if saved and saved[0] != self.station_id:
            raise ValueError('CONSOLE_VIEW_STORE_STATION_MISMATCH')
        db.execute('INSERT OR IGNORE INTO console_view_station VALUES (?)', (self.station_id,))
        db.execute("""CREATE TABLE IF NOT EXISTS console_renderer_sessions (
            session_id TEXT PRIMARY KEY, owner TEXT UNIQUE NOT NULL, epoch TEXT NOT NULL,
            revision INTEGER NOT NULL, last_seen REAL NOT NULL, closed INTEGER NOT NULL,
            state TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS console_view_requests (
            request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, epoch TEXT NOT NULL,
            payload TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
            status TEXT NOT NULL, outcome TEXT)""")

    @contextmanager
    def connection(self, initialize=False):
        if self.path.is_symlink():
            raise ValueError('CONSOLE_VIEW_STORE_SYMLINK')
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        uri = self.path.absolute().as_uri() + ('?mode=rwc' if initialize else '?mode=rw')
        db = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            if initialize:
                self.initialize_schema(db)
                os.chmod(self.path, 0o600)
            else:
                saved = db.execute('SELECT station_id FROM console_view_station').fetchone()
                if not saved or saved[0] != self.station_id:
                    raise ValueError('CONSOLE_VIEW_STORE_STATION_MISMATCH')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def decode_session(self, row):
        if row is None:
            return None
        value = dict(row)
        value['state'] = json.loads(value['state'])
        value['closed'] = bool(value['closed'])
        return value

    def decode_receipt(self, row):
        if row is None:
            return None
        value = dict(row)
        value['payload'] = json.loads(value['payload'])
        return value

    def create_session(self, owner, now, state):
        with self.connection(initialize=True) as db:
            existing = db.execute('SELECT * FROM console_renderer_sessions WHERE owner=?', (owner,)).fetchone()
            if existing:
                return self.decode_session(existing)
            session_id, epoch = uuid.uuid4().hex, uuid.uuid4().hex
            db.execute('INSERT INTO console_renderer_sessions VALUES (?,?,?,0,?,0,?)',
                       (session_id, owner, epoch, now, json.dumps(state, sort_keys=True)))
            return self.decode_session(db.execute('SELECT * FROM console_renderer_sessions WHERE session_id=?', (session_id,)).fetchone())

    def session(self, session_id):
        if not self.path.exists():
            return None
        with self.connection() as db:
            return self.decode_session(db.execute('SELECT * FROM console_renderer_sessions WHERE session_id=?', (session_id,)).fetchone())

    def sessions(self):
        if not self.path.exists():
            return []
        with self.connection() as db:
            return [self.decode_session(row) for row in db.execute('SELECT * FROM console_renderer_sessions ORDER BY last_seen DESC LIMIT 128')]

    def publish(self, session_id, epoch, owner, revision, now, state, closed=False):
        with self.connection() as db:
            row = db.execute('SELECT * FROM console_renderer_sessions WHERE session_id=?', (session_id,)).fetchone()
            if not row or row['epoch'] != epoch or row['owner'] != owner:
                raise ViewInteractionError('CONSOLE_RENDERER_OWNER_MISMATCH', 'forbidden')
            if row['closed'] or row['revision'] != revision:
                raise ViewInteractionError('CONSOLE_VIEW_REVISION_CONFLICT', 'conflict')
            encoded = json.dumps(state, sort_keys=True)
            changed = encoded != row['state'] or closed
            db.execute('UPDATE console_renderer_sessions SET state=?, revision=revision+?, last_seen=?, closed=? WHERE session_id=?',
                       (encoded, int(changed), now, int(closed), session_id))
            if closed:
                db.execute("UPDATE console_view_requests SET status='expired', outcome='renderer_closed' WHERE session_id=? AND status='accepted'", (session_id,))
            return self.decode_session(db.execute('SELECT * FROM console_renderer_sessions WHERE session_id=?', (session_id,)).fetchone())

    def enqueue(self, payload, now, lease, lifetime):
        encoded = json.dumps(payload, sort_keys=True)
        with self.connection() as db:
            existing = db.execute('SELECT * FROM console_view_requests WHERE request_id=?', (payload['request_id'],)).fetchone()
            if existing:
                if existing['payload'] != encoded:
                    raise ViewInteractionError('CONSOLE_VIEW_REQUEST_CONFLICT', 'conflict')
                return self.decode_receipt(existing)
            row = db.execute('SELECT * FROM console_renderer_sessions WHERE session_id=?', (payload['session_id'],)).fetchone()
            if not row or row['closed'] or row['last_seen'] + lease <= now:
                raise ViewInteractionError('CONSOLE_RENDERER_UNAVAILABLE', 'unavailable')
            if row['epoch'] != payload['epoch'] or row['revision'] != payload['expected_revision']:
                raise ViewInteractionError('CONSOLE_VIEW_REVISION_CONFLICT', 'conflict')
            count = db.execute("SELECT count(*) FROM console_view_requests WHERE session_id=? AND status='accepted' AND expires_at>?", (payload['session_id'], now)).fetchone()[0]
            if count >= 32:
                raise ViewInteractionError('CONSOLE_VIEW_QUEUE_FULL', 'conflict')
            db.execute("INSERT INTO console_view_requests VALUES (?,?,?,?,?,?,'accepted',NULL)",
                       (payload['request_id'], payload['session_id'], payload['epoch'], encoded, now, now+lifetime))
            return self.decode_receipt(db.execute('SELECT * FROM console_view_requests WHERE request_id=?', (payload['request_id'],)).fetchone())

    def receipt(self, request_id):
        if not self.path.exists():
            return None
        with self.connection() as db:
            return self.decode_receipt(db.execute('SELECT * FROM console_view_requests WHERE request_id=?', (request_id,)).fetchone())

    def pending(self, session_id, epoch):
        if not self.path.exists():
            return []
        with self.connection() as db:
            return [self.decode_receipt(row) for row in db.execute("SELECT * FROM console_view_requests WHERE session_id=? AND epoch=? AND status='accepted' ORDER BY created_at, rowid LIMIT 32", (session_id, epoch))]

    def acknowledge(self, session_id, epoch, owner, revision, request_id, outcome, state, now):
        with self.connection() as db:
            row = db.execute('SELECT * FROM console_renderer_sessions WHERE session_id=?', (session_id,)).fetchone()
            receipt = db.execute('SELECT * FROM console_view_requests WHERE request_id=?', (request_id,)).fetchone()
            if not row or row['owner'] != owner or row['epoch'] != epoch:
                raise ViewInteractionError('CONSOLE_RENDERER_OWNER_MISMATCH', 'forbidden')
            if not receipt or receipt['session_id'] != session_id or receipt['epoch'] != epoch:
                raise ViewInteractionError('CONSOLE_VIEW_REQUEST_NOT_FOUND', 'not_found')
            if receipt['status'] != 'accepted':
                if receipt['status'] == outcome:
                    return self.decode_session(row)
                raise ViewInteractionError('CONSOLE_VIEW_ACK_CONFLICT', 'conflict')
            if row['closed'] or row['revision'] != revision or receipt['expires_at'] <= now:
                raise ViewInteractionError('CONSOLE_VIEW_ACK_CONFLICT', 'conflict')
            encoded = json.dumps(state, sort_keys=True)
            db.execute('UPDATE console_renderer_sessions SET state=?, revision=revision+?, last_seen=? WHERE session_id=?',
                       (encoded, int(encoded != row['state']), now, session_id))
            db.execute('UPDATE console_view_requests SET status=?, outcome=? WHERE request_id=?', (outcome, 'renderer_report', request_id))
            return self.decode_session(db.execute('SELECT * FROM console_renderer_sessions WHERE session_id=?', (session_id,)).fetchone())
