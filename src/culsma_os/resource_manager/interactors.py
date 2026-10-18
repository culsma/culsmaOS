from contextlib import contextmanager
from .repository import ResourceRepository, ResourceInspectionRepository
from .models import ExecutionPermit, ResourceConflict


class ResourceInteractor:

    def __init__(self, repository: ResourceRepository, consumables, reservations=None):
        self.repository = repository
        self.consumables = consumables
        self.reservations = reservations

    def acquire(self, plan, attempt_id):
        parent = self.reservations.owned(plan.context.run_id) if self.reservations else None
        permit = ExecutionPermit(plan.effect_id, attempt_id, plan.context.resource_ids, parent)
        self.repository.acquire(permit)
        return permit

    def validate_permit(self, permit):
        self.repository.validate(permit)

    def authorize_dispatch(self, permit):
        self.repository.authorize(permit)

    def validate_active_permit(self, permit):
        self.repository.validate_authorized(permit)

    def settle(self, attempt_id, evidence):
        if (
            evidence.outcome in {"completed", "rejected"}
            and evidence.mode == "simulation"
        ):
            self.repository.release(attempt_id)

    def abandon_preparation(self, permit):
        self.repository.abandon_reserved(permit.attempt_id)

    def occupied(self):
        return self.repository.occupied()

    def active_attempts(self):
        return self.repository.active_attempts()

    def require_consumables(self, plan):
        self.consumables.require(
            plan.context.device_id, plan.description["resource_requirements"]
        )


class ConsumableInteractor:
    def __init__(self, device, evidence):
        self.device = device
        self.evidence = evidence

    def require(self, device_id, requirements):
        capacities = self.device.get(device_id).consumable_capacities
        consumed = self.evidence.known_consumption(device_id)
        if not isinstance(requirements, dict):
            raise ValueError("OS_RESOURCE_REQUIREMENTS_INVALID")
        for resource, amount in requirements.items():
            if not isinstance(resource, str) or type(amount) is not int or amount < 0:
                raise ValueError("OS_RESOURCE_REQUIREMENTS_INVALID")
            if (
                resource not in capacities
                or consumed.get(resource, 0) + amount > capacities[resource]
            ):
                raise ValueError("OS_CONSUMABLES_INSUFFICIENT")


class StationUsageInteractor:
    def __init__(self, repository):
        self.repository = repository

    def record(self, evidence, device_id):
        if evidence.mode != "simulation":
            raise ValueError("STATION_USAGE_MODE_UNSUPPORTED")
        if any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in evidence.consumed_resources.items()):
            raise ValueError("STATION_USAGE_INVALID")
        if evidence.consumed_resources:
            self.repository.record_usage(evidence.evidence_id, device_id, evidence.consumed_resources)

    def known(self, device_id, excluded_evidence_ids=()):
        return self.repository.usage(device_id, excluded_evidence_ids)


class RunReservationInteractor:
    def __init__(self, repository, safety, station_id, run_store, device, usage, owner_id=None):
        from uuid import uuid4
        self.repository, self.safety = repository, safety
        self.station_id, self.run_store, self.device = station_id, run_store, device
        self.usage = usage
        self.owner_id = owner_id or str(uuid4())

    def acquire(self, run_id):
        self.safety.require_run(run_id)
        resources = tuple(sorted({f"{self.device.mode}:device:{self.device.device_id}", *self.device.shared_resources}))
        return self.repository.claim(self.station_id, run_id, self.owner_id, self.run_store, resources)

    def owned(self, run_id):
        value = self.repository.get(run_id)
        if value is None or value.status != "active" or value.owner_id != self.owner_id or value.run_store != self.run_store:
            raise ResourceConflict("RUN_OWNER_STALE")
        self.repository.validate_owner(value)
        return value

    @contextmanager
    def run_guard(self, run_id):
        with self.repository.guard():
            value = self.owned(run_id)
            yield value

    @contextmanager
    def permit_guard(self, permit, run_id):
        with self.repository.guard():
            current = self.owned(run_id)
            if permit.run_reservation != current:
                raise ResourceConflict("RUN_OWNER_STALE")
            yield

    def take_over(self, run_id):
        self.safety.require_run(run_id)
        return self.repository.take_over(run_id, self.owner_id, self.run_store)

    def finish(self, run_id):
        with self.run_guard(run_id) as reservation:
            proof = self.safety.release_proof(run_id)
            if proof is None:
                return False
            self.safety.synchronize_usage(run_id)
            self.repository.release_run(reservation, proof)
            return True

    def get(self, run_id):
        return self.repository.get(run_id)

    def release_confirmation(self, run_id):
        from .models import RunReleaseConfirmation
        with self.repository.guard():
            value = self.repository.get(run_id)
            if value is None or value.status != "released" or value.run_store != self.run_store:
                return None
            stored = self.repository.release_proof(run_id)
            current = self.safety.release_proof(run_id)
            if (stored is None or current is None or stored.get("run_id") != run_id
                    or stored.get("mode") != "simulation" or type(stored.get("revision")) is not int
                    or stored.get("evidence_ids") != current["evidence_ids"]
                    or stored.get("reason") != current["reason"]
                    or stored.get("body_outcome", current["body_outcome"]) != current["body_outcome"]):
                return None
            return RunReleaseConfirmation(run_id, value.run_store, value.generation,
                stored["revision"], tuple(stored["evidence_ids"]))

    def released_safely(self, run_id):
        return self.release_confirmation(run_id) is not None

    @contextmanager
    def station_guard(self):
        with self.repository.guard():
            yield

    def run_stores(self):
        return self.repository.run_stores()

    def close(self):
        self.repository.close()


class StationPathInteractor:
    def database_path(self, context):
        import os
        from pathlib import Path
        from hashlib import sha256
        station_id = context.station_id or os.environ.get('CULSMA_OS_STATION_ID', 'local')
        station_root = context.station_root or Path(os.environ.get(
            'CULSMA_OS_STATION_ROOT', str(Path.home() / '.local/state/culsma-os/stations')))
        return station_root / (sha256(station_id.encode()).hexdigest() + '.sqlite3')

    def device_state_directory(self, context):
        from hashlib import sha256
        path = self.database_path(context)
        return path.parent / (path.stem + '-devices') / sha256(context.driver_name.encode()).hexdigest()


class ResourceInspectionInteractor:
    def __init__(self, repository: ResourceInspectionRepository, station):
        self.repository, self.station = repository, station

    def inspect(self):
        if self.station.active:
            return self.observe()
        with self.station:
            return self.observe()

    def observe(self):
        return {'locks': self.repository.locks(), 'permits': self.repository.permits(),
                'station_reservations': self.repository.reservations(),
                'station_locks': self.repository.station_locks(),
                'station_run_stores': self.repository.run_stores(),
                'station_usage': self.repository.usage(), **self.repository.accounting()}

    def consumables(self, device, evidence, resources, unresolved):
        totals = dict(evidence.known_consumption)
        local_ids = set(evidence.evidence_ids)
        for record in resources['station_usage']:
            if record['device_id'] == device.device_id and record['evidence_id'] not in local_ids:
                for name, amount in record['consumption'].items():
                    totals[name] = totals.get(name, 0) + amount
        # Parent ownership can span a different run store: do not infer idleness from local attempts alone.
        occupied = bool(resources['permits'] or resources['locks'] or resources['station_reservations']
                        or resources['station_locks'])
        uncertain = bool(unresolved or occupied or evidence.accounting != 'recorded'
                         or resources['local_accounting'] != 'recorded'
                         or resources['station_accounting'] != 'recorded')
        return {name: {'configured_capacity': capacity, 'known_consumed': totals.get(name, 0),
            'remaining_upper_bound': max(0, capacity - totals.get(name, 0)),
            'available_from_records': None if uncertain else max(0, capacity - totals.get(name, 0)),
            'status': 'unknown' if uncertain else 'recorded'}
            for name, capacity in device.consumable_capacities.items()}
