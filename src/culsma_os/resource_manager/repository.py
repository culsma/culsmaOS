from contextlib import contextmanager
import json
from typing import Protocol
from .models import ExecutionPermit, ResourceConflict


class ResourceRepository(Protocol):

    def acquire(self, permit: ExecutionPermit) -> None: ...

    def authorize(self, permit: ExecutionPermit) -> None: ...

    def validate_authorized(self, permit: ExecutionPermit) -> None: ...

    def validate(self, permit: ExecutionPermit) -> None: ...

    def release(self, attempt_id: str) -> None: ...

    def occupied(self) -> tuple[str, ...]: ...

    def abandon_reserved(self, attempt_id: str) -> None: ...

    def active_attempts(self) -> tuple[str, ...]: ...


class SqliteResourceRepository:

    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_resource_locks(resource_id TEXT PRIMARY KEY,attempt_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_permits(attempt_id TEXT PRIMARY KEY,effect_id TEXT,resources TEXT,status TEXT)"
            )

    def acquire(self, permit):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT effect_id,resources,status FROM os_permits WHERE attempt_id=?",
                (permit.attempt_id,),
            ).fetchone()
            if existing:
                if existing != (
                    permit.effect_id,
                    json.dumps(permit.resources),
                    "reserved",
                ):
                    raise ResourceConflict("PERMIT_ALREADY_DISPATCHED")
                self.validate(permit)
                return
            for resource in permit.resources:
                if self.connection.execute(
                    "SELECT 1 FROM os_resource_locks WHERE resource_id=?", (resource,)
                ).fetchone():
                    raise ResourceConflict("RESOURCE_OCCUPIED")
                self.connection.execute(
                    "INSERT INTO os_resource_locks VALUES(?,?)",
                    (resource, permit.attempt_id),
                )
            self.connection.execute(
                "INSERT INTO os_permits VALUES(?,?,?,'reserved')",
                (permit.attempt_id, permit.effect_id, json.dumps(permit.resources)),
            )

    def validate(self, permit):
        row = self.connection.execute(
            "SELECT effect_id,resources,status FROM os_permits WHERE attempt_id=?",
            (permit.attempt_id,),
        ).fetchone()
        if row != (permit.effect_id, json.dumps(permit.resources), "reserved"):
            raise ResourceConflict("PERMIT_INVALID")
        for resource in permit.resources:
            row = self.connection.execute(
                "SELECT attempt_id FROM os_resource_locks WHERE resource_id=?",
                (resource,),
            ).fetchone()
            if row != (permit.attempt_id,):
                raise ResourceConflict("RESOURCE_OWNERSHIP_LOST")

    def validate_authorized(self, permit):
        row = self.connection.execute("SELECT effect_id,resources,status FROM os_permits WHERE attempt_id=?", (permit.attempt_id,)).fetchone()
        if row != (permit.effect_id, json.dumps(permit.resources), "authorized"):
            raise ResourceConflict("GROUP_PERMIT_NOT_AUTHORIZED")
        if any(self.connection.execute("SELECT attempt_id FROM os_resource_locks WHERE resource_id=?", (resource,)).fetchone() != (permit.attempt_id,) for resource in permit.resources):
            raise ResourceConflict("RESOURCE_OWNERSHIP_LOST")

    def authorize(self, permit):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.validate(permit)
            self.connection.execute(
                "UPDATE os_permits SET status='authorized' WHERE attempt_id=?",
                (permit.attempt_id,),
            )

    def release(self, attempt_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM os_resource_locks WHERE attempt_id=?", (attempt_id,)
            )
            self.connection.execute(
                "UPDATE os_permits SET status='released' WHERE attempt_id=?",
                (attempt_id,),
            )

    def abandon_reserved(self, attempt_id):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT status FROM os_permits WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row != ("reserved",):
                raise ResourceConflict("PERMIT_MAY_BE_ACTIVE")
            self.connection.execute(
                "DELETE FROM os_resource_locks WHERE attempt_id=?", (attempt_id,)
            )
            self.connection.execute(
                "UPDATE os_permits SET status='released' WHERE attempt_id=?",
                (attempt_id,),
            )

    def occupied(self):
        return tuple(
            (
                r[0]
                for r in self.connection.execute(
                    "SELECT resource_id FROM os_resource_locks ORDER BY resource_id"
                )
            )
        )

    def active_attempts(self):
        return tuple(
            (
                row[0]
                for row in self.connection.execute(
                    "SELECT attempt_id FROM os_permits WHERE status!='released'"
                )
            )
        )


class RunReservationRepository(Protocol):
    def run_stores(self): ...
    def guard(self): ...
    def claim(self, station_id, run_id, owner_id, run_store, resources): ...
    def get(self, run_id): ...
    def take_over(self, run_id, owner_id, run_store): ...
    def validate_owner(self, reservation): ...
    def release_run(self, reservation, proof): ...
    def release_proof(self, run_id): ...
    def record_usage(self, evidence_id, device_id, consumption): ...
    def usage(self, device_id, excluded_evidence_ids=()): ...


class SqliteRunReservationRepository:
    """Station persistence and a process-shared POSIX dispatch guard."""

    def __init__(self, connection, guard_path):
        import os
        from threading import RLock, local
        self.connection = connection
        self.lock = RLock()
        self.depth = local()
        self.guard_fd = os.open(guard_path, os.O_RDWR | os.O_CREAT, 0o600)
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS os_run_reservations(run_id TEXT PRIMARY KEY,record TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS os_run_resources(resource_id TEXT PRIMARY KEY,run_id TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS os_run_releases(run_id TEXT PRIMARY KEY,proof TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS os_station_usage(evidence_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,consumption TEXT NOT NULL)")

    @contextmanager
    def guard(self):
        import fcntl
        if not self.lock.acquire(blocking=False):
            raise ResourceConflict("STATION_DISPATCH_ACTIVE")
        outer = not getattr(self.depth, "value", 0)
        try:
            if outer:
                try:
                    fcntl.flock(self.guard_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ResourceConflict("STATION_DISPATCH_ACTIVE") from error
            self.depth.value = getattr(self.depth, "value", 0) + 1
            try:
                yield
            finally:
                self.depth.value -= 1
                if outer:
                    fcntl.flock(self.guard_fd, fcntl.LOCK_UN)
        finally:
            self.lock.release()

    def get(self, run_id):
        from .models import RunReservation
        row = self.connection.execute("SELECT record FROM os_run_reservations WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        value = json.loads(row[0]); value["resources"] = tuple(value["resources"])
        return RunReservation(**value)

    def store(self, reservation):
        from dataclasses import asdict
        self.connection.execute("INSERT INTO os_run_reservations VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET record=excluded.record",
                                (reservation.run_id, json.dumps(asdict(reservation), sort_keys=True)))

    def claim(self, station_id, run_id, owner_id, run_store, resources):
        from .models import RunReservation
        with self.guard(), self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.get(run_id)
            if existing:
                if existing.run_store != run_store or existing.station_id != station_id:
                    raise ResourceConflict("RUN_STORE_MISMATCH")
                if existing.status != "active":
                    raise ResourceConflict("RUN_RESERVATION_CLOSED")
                if existing.owner_id != owner_id:
                    raise ResourceConflict("RUN_OWNER_STALE: explicit takeover required")
                if existing.resources != resources:
                    raise ResourceConflict("RUN_RESOURCE_SET_CHANGED")
                self.validate_owner(existing)
                return existing
            for resource in resources:
                if self.connection.execute("SELECT run_id FROM os_run_resources WHERE resource_id=?", (resource,)).fetchone():
                    raise ResourceConflict("RUN_RESERVATION_OCCUPIED")
                self.connection.execute("INSERT INTO os_run_resources VALUES(?,?)", (resource, run_id))
            value = RunReservation(station_id, run_id, owner_id, 1, run_store, resources)
            self.store(value)
            return value

    def validate_owner(self, reservation):
        current = self.get(reservation.run_id)
        if current != reservation or current.status != "active":
            raise ResourceConflict("RUN_OWNER_STALE")
        if any(self.connection.execute("SELECT run_id FROM os_run_resources WHERE resource_id=?", (resource,)).fetchone() != (reservation.run_id,)
               for resource in reservation.resources):
            raise ResourceConflict("RUN_RESERVATION_OWNERSHIP_LOST")

    def take_over(self, run_id, owner_id, run_store):
        from dataclasses import replace
        with self.guard(), self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.get(run_id)
            if existing is None or existing.status != "active":
                raise ResourceConflict("RUN_RESERVATION_CLOSED")
            if existing.run_store != run_store:
                raise ResourceConflict("RUN_STORE_MISMATCH")
            self.validate_owner(existing)
            value = replace(existing, owner_id=owner_id, generation=existing.generation + 1)
            self.store(value)
            return value

    def release_run(self, reservation, proof):
        from dataclasses import replace
        with self.guard(), self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.validate_owner(reservation)
            self.connection.execute("DELETE FROM os_run_resources WHERE run_id=?", (reservation.run_id,))
            self.store(replace(reservation, status="released"))
            self.connection.execute("INSERT INTO os_run_releases VALUES(?,?)", (reservation.run_id, json.dumps(proof, sort_keys=True)))

    def release_proof(self, run_id):
        row = self.connection.execute("SELECT proof FROM os_run_releases WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def record_usage(self, evidence_id, device_id, consumption):
        encoded = json.dumps(consumption, sort_keys=True)
        existing = self.connection.execute("SELECT device_id,consumption FROM os_station_usage WHERE evidence_id=?", (evidence_id,)).fetchone()
        if existing == (device_id, encoded):
            return
        with self.guard(), self.connection:
            row = self.connection.execute("SELECT device_id,consumption FROM os_station_usage WHERE evidence_id=?", (evidence_id,)).fetchone()
            if row and row != (device_id, encoded):
                raise ValueError("STATION_USAGE_CONFLICT")
            self.connection.execute("INSERT OR IGNORE INTO os_station_usage VALUES(?,?,?)", (evidence_id, device_id, encoded))

    def usage(self, device_id, excluded_evidence_ids=()):
        excluded = set(excluded_evidence_ids)
        totals = {}
        for identity, encoded in self.connection.execute("SELECT evidence_id,consumption FROM os_station_usage WHERE device_id=?", (device_id,)):
            if identity in excluded:
                continue
            for resource, amount in json.loads(encoded).items():
                totals[resource] = totals.get(resource, 0) + amount
        return totals

    def run_stores(self):
        return tuple(sorted({json.loads(row[0])['run_store'] for row in self.connection.execute(
            'SELECT record FROM os_run_reservations')}))

    def close(self):
        import os
        os.close(self.guard_fd)
        self.connection.close()


class ResourceInspectionRepository(Protocol):
    def accounting(self): ...
    def locks(self): ...
    def permits(self): ...
    def reservations(self): ...
    def station_locks(self): ...
    def run_stores(self): ...
    def usage(self): ...


class SqliteResourceInspectionRepository:
    def __init__(self, local, station):
        self.local, self.station = local, station

    def accounting(self):
        return {'local_accounting': 'recorded' if {'os_resource_locks', 'os_permits'} <= self.local.tables else 'unavailable',
                'station_accounting': 'recorded' if {'os_station_usage', 'os_run_reservations',
                    'os_run_resources'} <= self.station.tables else 'unavailable'}

    def locks(self):
        return [dict(zip(('resource_id', 'attempt_id'), row)) for row in self.local.rows(
            'os_resource_locks', 'SELECT resource_id,attempt_id FROM os_resource_locks ORDER BY resource_id')]

    def permits(self):
        return [{'attempt_id': row[0], 'effect_id': row[1], 'resources': json.loads(row[2]), 'status': row[3]}
            for row in self.local.rows('os_permits',
                "SELECT attempt_id,effect_id,resources,status FROM os_permits WHERE status != 'released' ORDER BY attempt_id")]

    def reservations(self):
        records = [json.loads(row[0]) for row in self.station.rows(
            'os_run_reservations', 'SELECT record FROM os_run_reservations ORDER BY run_id')]
        return [r for r in records if r['status'] == 'active']

    def run_stores(self):
        return sorted({json.loads(row[0])['run_store'] for row in self.station.rows(
            'os_run_reservations', 'SELECT record FROM os_run_reservations')})

    def station_locks(self):
        return [dict(zip(('resource_id', 'run_id'), row)) for row in self.station.rows(
            'os_run_resources', 'SELECT resource_id,run_id FROM os_run_resources ORDER BY resource_id')]

    def usage(self):
        return [{'evidence_id': row[0], 'device_id': row[1], 'consumption': json.loads(row[2])}
            for row in self.station.rows('os_station_usage',
                'SELECT evidence_id,device_id,consumption FROM os_station_usage ORDER BY evidence_id')]
