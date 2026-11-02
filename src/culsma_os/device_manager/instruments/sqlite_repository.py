"""Append-only profile revisions in an owner-supplied standalone SQLite database."""
import json
from uuid import uuid4
from .models import InstrumentModule, ProfileReference, ModuleProfileDraft, ModuleProfileRevision, ModuleProfileError
from .values import plain_value
from .applicability import ProfileApplicabilityInteractor


class SqliteModuleProfileRepository:
    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS module_profile_revisions (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL, module_id TEXT NOT NULL, profile_id TEXT NOT NULL,
                revision TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)""")
            connection.execute("""CREATE INDEX IF NOT EXISTS module_profile_lookup
                ON module_profile_revisions(device_id,module_id,profile_id,revision)""")

    def encode(self, profile):
        module = profile.module
        return json.dumps({'reference': vars(profile.reference),
            'module': {'device_id': module.device_id, 'module_id': module.module_id,
                       'kind': module.kind, 'driver_id': module.driver_id,
                       'configuration_revision': module.configuration_revision,
                       'shared_resource_ids': list(module.shared_resource_ids)},
            'method_id': profile.method_id, 'definition_revision': profile.definition_revision,
            'display_name': profile.display_name, 'parameters': plain_value(profile.parameters),
            'applicability': ProfileApplicabilityInteractor().encode(profile.applicability)},
            sort_keys=True, allow_nan=False)

    def decode(self, payload):
        value = json.loads(payload)
        module = value['module']
        module['shared_resource_ids'] = tuple(module['shared_resource_ids'])
        return ModuleProfileRevision(ProfileReference(**value['reference']), InstrumentModule(**module),
            value['method_id'], value['definition_revision'], value['display_name'], value['parameters'],
            ProfileApplicabilityInteractor().parse(value.get('applicability')))

    def get_revision(self, reference: ProfileReference):
        row = self.connection.execute('SELECT payload FROM module_profile_revisions WHERE device_id=? AND module_id=? AND profile_id=? AND revision=?',
            (reference.device_id, reference.module_id, reference.profile_id, reference.revision)).fetchone()
        if row is None:
            raise ModuleProfileError('PROFILE_REVISION_NOT_FOUND')
        return self.decode(row[0])

    def list_profiles(self, device_id, module_id):
        rows = self.connection.execute('SELECT payload FROM module_profile_revisions WHERE device_id=? AND module_id=? ORDER BY sequence', (device_id, module_id))
        return tuple(self.decode(row[0]) for row in rows)

    def save_revision(self, draft: ModuleProfileDraft):
        if not draft.profile_id or not draft.display_name:
            raise ModuleProfileError('PROFILE_IDENTITY_REQUIRED')
        if self.connection.in_transaction:
            raise ModuleProfileError('PROFILE_TRANSACTION_ALREADY_OPEN')
        module = draft.module
        key = (module.device_id, module.module_id, draft.profile_id)
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            row = self.connection.execute('SELECT revision FROM module_profile_revisions WHERE device_id=? AND module_id=? AND profile_id=? ORDER BY sequence DESC LIMIT 1', key).fetchone()
            current = row[0] if row else None
            if current != draft.expected_revision:
                raise ModuleProfileError('PROFILE_REVISION_CONFLICT')
            reference = ProfileReference(*key, str(uuid4()))
            result = ModuleProfileRevision(reference, module, draft.method_id,
                draft.definition_revision, draft.display_name, draft.parameters, draft.applicability)
            self.connection.execute('INSERT INTO module_profile_revisions(device_id,module_id,profile_id,revision,payload) VALUES(?,?,?,?,?)',
                (*key, reference.revision, self.encode(result)))
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise


class FileModuleProfileRepository:
    """Same revision store with operation-scoped connections for HTTP and MCP."""
    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path)

    def list_profiles(self, device_id, module_id):
        from contextlib import closing
        import sqlite3
        if not self.path.exists():
            return ()
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            return SqliteModuleProfileRepository(connection).list_profiles(device_id, module_id)

    def get_revision(self, reference):
        from contextlib import closing
        import sqlite3
        if not self.path.exists():
            raise ModuleProfileError('PROFILE_REVISION_NOT_FOUND')
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            return SqliteModuleProfileRepository(connection).get_revision(reference)

    def save_revision(self, draft):
        from contextlib import closing
        import sqlite3
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            return SqliteModuleProfileRepository(connection).save_revision(draft)


class FileRunProfileBindingRepository:
    """Immutable selections captured before run admission; no latest lookup at dispatch."""
    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path)

    def save(self, run_id, profiles):
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            codec = SqliteModuleProfileRepository(connection)
            payload = json.dumps({step: codec.encode(profile) for step, profile in profiles.items()}, sort_keys=True)
            connection.execute('CREATE TABLE IF NOT EXISTS instrument_run_profiles(run_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            row = connection.execute('SELECT payload FROM instrument_run_profiles WHERE run_id=?', (run_id,)).fetchone()
            if row is not None and row[0] != payload:
                raise ModuleProfileError('PROFILE_RUN_BINDING_CONFLICT')
            connection.execute('INSERT OR IGNORE INTO instrument_run_profiles VALUES(?,?)', (run_id, payload))

    def get(self, run_id):
        from contextlib import closing
        import sqlite3
        if not self.path.exists(): return {}
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='instrument_run_profiles'").fetchone() is None:
                return {}
            row = connection.execute('SELECT payload FROM instrument_run_profiles WHERE run_id=?', (run_id,)).fetchone()
            if row is None: return {}
            codec = SqliteModuleProfileRepository(connection)
            return {step: codec.decode(profile) for step, profile in json.loads(row[0]).items()}
