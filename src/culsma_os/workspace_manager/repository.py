import json
from dataclasses import asdict
from typing import Protocol
from .models import ResolvedContainerRef
from .models import LayoutSnapshot, SpaceBinding


class SpaceRepository(Protocol):

    def put(self, snapshot: LayoutSnapshot) -> None: ...

    def get(self, run_id: str) -> LayoutSnapshot: ...


class SqliteSpaceRepository:

    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_layouts(run_id TEXT PRIMARY KEY,snapshot TEXT)"
            )

    def put(self, snapshot):
        with self.connection:
            self.connection.execute(
                "INSERT INTO os_layouts VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET snapshot=excluded.snapshot",
                (snapshot.run_id, json.dumps(asdict(snapshot))),
            )

    def get(self, run_id):
        row = self.connection.execute(
            "SELECT snapshot FROM os_layouts WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        data = json.loads(row[0])
        data["bindings"] = tuple(
            (
                SpaceBinding(
                    ResolvedContainerRef(b["reference"]["container_id"]),
                    b["labware"],
                    b["well"],
                    b["capacity_uL"],
                    b["allocation_step_id"],
                    b.get("carrier_id"),
                    b.get("carrier_namespace"),
                    b.get("carrier_position"),
                    tuple(b["carrier_geometry"]) if b.get("carrier_geometry") is not None else None,
                    b.get("carrier_instance_id"),
                )
                for b in data["bindings"]
            )
        )
        return LayoutSnapshot(**data)


class LabwarePositionRepository(Protocol):
    def get(self, device_id): ...
    def registration(self, effect_id): ...
    def apply(self, device_id, configuration_revision, initial, expected_revision, positions, registration): ...
    def initialize(self, device_id, configuration_revision, initial): ...
    def legacy_position(self, device_id): ...
    def legacy_registrations(self, effect_ids): ...
    def adopt(self, device_id, position, registrations, digest): ...
    def pending(self, device_id): ...
    def record_pending(self, device_id, record): ...
    def reject(self, effect_id): ...


class SqliteLabwarePositionRepository:
    def __init__(self, connection, legacy=None, run_store=None):
        self.connection, self.legacy, self.run_store = connection, legacy, run_store
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS os_labware_positions(device_id TEXT PRIMARY KEY,configuration_revision TEXT,revision INTEGER,positions TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS os_motion_registrations(effect_id TEXT PRIMARY KEY,record TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS os_station_motion_intents(effect_id TEXT PRIMARY KEY,device_id TEXT,record TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS os_workspace_imports(run_store TEXT,device_id TEXT,digest TEXT,PRIMARY KEY(run_store,device_id))")

    def get(self, device_id):
        row = self.connection.execute("SELECT configuration_revision,revision,positions FROM os_labware_positions WHERE device_id=?", (device_id,)).fetchone()
        return None if row is None else (row[0], row[1], json.loads(row[2]))

    def registration(self, effect_id):
        row = self.connection.execute("SELECT record FROM os_motion_registrations WHERE effect_id=?", (effect_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def apply(self, device_id, configuration_revision, initial, expected_revision, positions, registration):
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO os_labware_positions VALUES(?,?,0,?)", (device_id, configuration_revision, json.dumps(initial, sort_keys=True)))
            cursor = self.connection.execute("UPDATE os_labware_positions SET revision=revision+1,positions=? WHERE device_id=? AND configuration_revision=? AND revision=?",
                (json.dumps(positions, sort_keys=True), device_id, configuration_revision, expected_revision))
            if cursor.rowcount != 1:
                raise ValueError("MOTION_POSITION_REVISION_CONFLICT")
            self.connection.execute("INSERT INTO os_motion_registrations VALUES(?,?)", (registration["effect_id"], json.dumps(registration, sort_keys=True)))
            self.connection.execute('DELETE FROM os_station_motion_intents WHERE effect_id=?', (registration['effect_id'],))


    def initialize(self, device_id, configuration_revision, initial):
        with self.connection:
            self.connection.execute('INSERT OR IGNORE INTO os_labware_positions VALUES(?,?,0,?)',
                                    (device_id, configuration_revision, json.dumps(initial, sort_keys=True)))

    def legacy_rows(self, table, statement, parameters=()):
        if self.legacy is None or not self.legacy.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            return ()
        return tuple(self.legacy.execute(statement, parameters))

    def legacy_position(self, device_id):
        rows = self.legacy_rows('os_labware_positions',
            'SELECT configuration_revision,revision,positions FROM os_labware_positions WHERE device_id=?', (device_id,))
        return None if not rows else (rows[0][0], rows[0][1], json.loads(rows[0][2]))

    def legacy_registrations(self, effect_ids):
        return {row[0]: json.loads(row[1]) for row in self.legacy_rows(
            'os_motion_registrations', 'SELECT effect_id,record FROM os_motion_registrations') if row[0] in effect_ids}

    def adopt(self, device_id, position, registrations, digest):
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            imported = self.connection.execute('SELECT digest FROM os_workspace_imports WHERE run_store=? AND device_id=?',
                                                (self.run_store, device_id)).fetchone()
            if imported:
                if imported[0] != digest:
                    raise ValueError('STATION_WORKSPACE_LEGACY_CHANGED')
                return
            current = self.get(device_id)
            if current is not None and current != position:
                raise ValueError('STATION_WORKSPACE_LEGACY_CONFLICT')
            for effect, record in registrations.items():
                old = self.registration(effect)
                if (old is not None and old != record) or (current is not None and old is None):
                    raise ValueError('STATION_WORKSPACE_PROOF_CONFLICT')
                self.connection.execute('INSERT OR IGNORE INTO os_motion_registrations VALUES(?,?)',
                                        (effect, json.dumps(record, sort_keys=True)))
            self.connection.execute('INSERT OR IGNORE INTO os_labware_positions VALUES(?,?,?,?)',
                (device_id, position[0], position[1], json.dumps(position[2], sort_keys=True)))
            self.connection.execute('INSERT INTO os_workspace_imports VALUES(?,?,?)', (self.run_store, device_id, digest))

    def pending(self, device_id):
        return tuple(json.loads(row[0]) for row in self.connection.execute(
            'SELECT record FROM os_station_motion_intents WHERE device_id=? ORDER BY effect_id', (device_id,)))

    def record_pending(self, device_id, record):
        encoded = json.dumps(record, sort_keys=True)
        record = json.loads(encoded)
        effect = record['attempt']['effect_id']
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            if self.registration(effect) is not None:
                return
            old = self.connection.execute('SELECT record FROM os_station_motion_intents WHERE effect_id=?', (effect,)).fetchone()
            if old and any(json.loads(old[0])[key] != record[key] for key in ('attempt', 'run_store')):
                raise ValueError('STATION_MOTION_INTENT_CONFLICT')
            self.connection.execute('INSERT INTO os_station_motion_intents VALUES(?,?,?) ON CONFLICT(effect_id) DO UPDATE SET record=excluded.record',
                                    (effect, device_id, encoded))

    def reject(self, effect_id):
        with self.connection:
            self.connection.execute('DELETE FROM os_station_motion_intents WHERE effect_id=?', (effect_id,))


class WorkspaceInspectionRepository(Protocol):
    def position(self, device_id): ...
    def registrations(self): ...
    def scope(self, device_id): ...
    def pending(self, device_id): ...


class SqliteWorkspaceInspectionRepository:
    def __init__(self, snapshot, legacy=None):
        self.snapshot, self.legacy = snapshot, legacy

    def position_from(self, source, device_id):
        rows = source.rows('os_labware_positions',
            'SELECT configuration_revision,revision,positions FROM os_labware_positions WHERE device_id=?', (device_id,))
        return None if not rows else (rows[0][0], rows[0][1], json.loads(rows[0][2]))

    def position(self, device_id):
        current = self.position_from(self.snapshot, device_id)
        return current if current is not None or self.legacy is None else self.position_from(self.legacy, device_id)

    def scope(self, device_id):
        return 'station' if self.position_from(self.snapshot, device_id) is not None else 'run_store_legacy'

    def registrations(self):
        sources = (self.legacy, self.snapshot) if self.legacy is not None else (self.snapshot,)
        result = {}
        for source in sources:
            result.update({row[0]: json.loads(row[1]) for row in source.rows(
                'os_motion_registrations', 'SELECT effect_id,record FROM os_motion_registrations')})
        return result

    def pending(self, device_id):
        return tuple(json.loads(row[0]) for row in self.snapshot.rows('os_station_motion_intents',
            'SELECT record FROM os_station_motion_intents WHERE device_id=? ORDER BY effect_id', (device_id,)))
