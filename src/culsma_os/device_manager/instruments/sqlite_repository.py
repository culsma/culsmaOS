"""Append-only profile revisions in an owner-supplied standalone SQLite database."""
import json
from uuid import uuid4
from .models import InstrumentModule, ProfileReference, ModuleProfileDraft, ModuleProfileRevision, ModuleProfileError
from .values import plain_value


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
            'display_name': profile.display_name, 'parameters': plain_value(profile.parameters)},
            sort_keys=True, allow_nan=False)

    def decode(self, payload):
        value = json.loads(payload)
        module = value['module']
        module['shared_resource_ids'] = tuple(module['shared_resource_ids'])
        return ModuleProfileRevision(ProfileReference(**value['reference']), InstrumentModule(**module),
            value['method_id'], value['definition_revision'], value['display_name'], value['parameters'])

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
                draft.definition_revision, draft.display_name, draft.parameters)
            self.connection.execute('INSERT INTO module_profile_revisions(device_id,module_id,profile_id,revision,payload) VALUES(?,?,?,?,?)',
                (*key, reference.revision, self.encode(result)))
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise
