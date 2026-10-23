"""Durable per-run setup plans; compare-and-swap revisions protect confirmations."""
from typing import Protocol
from copy import deepcopy
import json


class RunSetupRepository(Protocol):
    def get(self, run_id): ...
    def save(self, run_id, document, expected_revision): ...


class SqliteRunSetupRepository:
    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute('CREATE TABLE IF NOT EXISTS os_setup_requests(request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT, error TEXT, done INTEGER NOT NULL DEFAULT 0)')
            connection.execute("CREATE INDEX IF NOT EXISTS os_setup_requests_run ON os_setup_requests(json_extract(payload, '$.run_id'))")
            connection.execute('CREATE TABLE IF NOT EXISTS os_run_setups(run_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL)')

    def get(self, run_id):
        row = self.connection.execute('SELECT revision,document FROM os_run_setups WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {**json.loads(row[1]), 'revision': row[0]}

    def save(self, run_id, document, expected_revision):
        content = deepcopy(document)
        content.pop('revision', None)
        encoded = json.dumps(content, sort_keys=True, allow_nan=False)
        with self.connection:
            if expected_revision == 0:
                changed = self.connection.execute('INSERT OR IGNORE INTO os_run_setups VALUES(?,1,?)', (run_id, encoded)).rowcount
            else:
                changed = self.connection.execute('UPDATE os_run_setups SET revision=revision+1,document=? WHERE run_id=? AND revision=?',
                    (encoded, run_id, expected_revision)).rowcount
            if changed != 1:
                raise ValueError('SETUP_REVISION_CONFLICT')
        return self.get(run_id)

    def enqueue(self, request_id, payload):
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        with self.connection:
            self.connection.execute('INSERT OR IGNORE INTO os_setup_requests(request_id,payload) VALUES(?,?)', (request_id, encoded))
            row = self.connection.execute('SELECT payload FROM os_setup_requests WHERE request_id=?', (request_id,)).fetchone()
            if row[0] != encoded:
                raise ValueError('SETUP_REQUEST_ID_CONFLICT')
        return self.request(request_id)

    def request(self, request_id):
        row = self.connection.execute('SELECT payload,result,error,done FROM os_setup_requests WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        return {'request_id': request_id, **json.loads(row[0]), 'result': json.loads(row[1]) if row[1] else None,
                'error': row[2], 'status': 'failed' if row[2] else 'completed' if row[3] else 'pending'}

    def pending_requests(self):
        rows = self.connection.execute('SELECT request_id FROM os_setup_requests WHERE done=0 ORDER BY rowid').fetchall()
        return tuple(self.request(row[0]) for row in rows)

    def settle_request(self, request_id, result=None, error=None):
        with self.connection:
            self.connection.execute('UPDATE os_setup_requests SET result=?,error=?,done=1 WHERE request_id=? AND done=0',
                (json.dumps(result, sort_keys=True, allow_nan=False), error, request_id))

    def activity(self, run_id):
        # Audit labels are observations, never credential or authorization facts.
        rows = self.connection.execute("SELECT request_id,payload,error,done FROM os_setup_requests WHERE json_extract(payload, '$.run_id')=? ORDER BY rowid DESC LIMIT 20", (run_id,)).fetchall()
        values = []
        for request_id, payload, error, done in rows:
            value = json.loads(payload)
            values.append({'request_id':request_id,'action':value['action'],'origin':value.get('origin','local-cli'),
                           'status':'failed' if error else 'completed' if done else 'pending','error':error})
        return values
