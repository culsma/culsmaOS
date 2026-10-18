from .repository import HostLeaseRepository, ResidentConfigurationRepository

class LifecycleInteractor:

    def __init__(
        self, tasks, runs, operations, recovery, state, device, evidence, device_id, conditions=None, finalization=None
    ):
        self.tasks = tasks
        self.runs = runs
        self.operations = operations
        self.recovery = recovery
        self.state = state
        self.device = device
        self.evidence = evidence
        self.device_id = device_id
        self.ready = False
        self.conditions = conditions
        self.finalization = finalization
        self.reservations = operations.resource.reservations

    def start_and_reconcile(self):
        if self.ready:
            return ()
        if self.operations.motions is not None:
            self.operations.motions.motion.initialize(self.evidence, self.reservations)
        self.evidence.synchronize_device_usage(self.device_id)
        self.device.restore_consumables(self.device_id, self.evidence)
        decisions = self.recovery.reconcile_unfinished_runs()
        self.state.publish_pending_events()
        self.ready = True
        return decisions

    def advance_once(self, run_id):
        if not self.ready:
            raise ValueError("OS_NOT_STARTED")
        self.state.publish_pending_events()
        record = self.tasks.get(run_id)
        if record.status not in {"ready", "waiting"}:
            return self.finish_terminal(record)
        if record.status == "ready":
            record = self.runs.advance_ready(run_id)
        if record.status == "waiting":
            self.operations.dispatch_ready(run_id)
            record = self.tasks.get(run_id)
        if record.status not in {"ready", "waiting"}:
            return self.finish_terminal(record)
        return record

    def run_until_settled(self, run_id):
        if not self.ready:
            raise ValueError("OS_NOT_STARTED")
        for _ in range(10000):
            before = self.tasks.get(run_id)
            record = self.advance_once(run_id)
            if record.status not in {"ready", "waiting"} or record.revision == before.revision:
                return record
        raise RuntimeError("OS_LIFECYCLE_GUARD")

    def stop_and_reconcile(self):
        self.ready = False


    def finish_terminal(self, record):
        result = self.finalization.finalize(record.run_id)
        self.state.publish_pending_events()
        return result

    def take_over_run(self, run_id):
        from culsma_os.recovery_manager.models import RecoveryDecision
        record = self.tasks.get(run_id)
        owner = self.reservations.get(run_id)
        if owner is not None and owner.status == "released":
            self.finalization.finalize(run_id)
            return RecoveryDecision(run_id, "unchanged", "RUN_ALREADY_RELEASED")
        if owner is None and record.body_outcome is not None:
            self.finalization.finalize(run_id)
            return RecoveryDecision(run_id, "unchanged", "NO_ACTIVE_RESERVATION")
        if owner is not None:
            self.device.require_session_configuration()
        if owner is None:
            self.reservations.acquire(run_id)
        elif owner.owner_id != self.reservations.owner_id:
            self.reservations.take_over(run_id)
        with self.reservations.run_guard(run_id):
            self.device.admit_session(allow_reconfiguration=owner is None)
            return self.recovery.reconcile(run_id)

    def pause_run(self, run_id):
        return self.tasks.pause_dispatch(run_id)

    def resume_run(self, run_id):
        record = self.tasks.get(run_id)
        if record.body_outcome is not None or record.status in {"completed", "failed", "cancelled"}:
            return self.finalization.finalize(run_id)
        if self.reservations.get(run_id) is None:
            return self.tasks.resume_dispatch(run_id)
        with self.reservations.run_guard(run_id):
            return self.tasks.resume_dispatch(run_id)

    def cancel_run(self, run_id):
        from culsma_os.resource_manager.models import ResourceConflict
        record = self.tasks.request_cancel(run_id)
        try:
            return self.finish_terminal(record)
        except ResourceConflict:
            return record


class RunFinalizationInteractor:
    """One idempotent completion path for normal execution and crash recovery."""

    def __init__(self, tasks, state, safety, reservations, conditions, resource, evidence):
        self.tasks, self.state, self.safety = tasks, state, safety
        self.reservations, self.conditions = reservations, conditions
        self.resource, self.evidence = resource, evidence

    def finalize(self, run_id):
        record = self.tasks.get(run_id)
        if record.status in {"completed", "failed", "cancelled"}:
            return record
        if record.body_outcome is None and record.status != "cancel_requested":
            return record
        owner = self.reservations.get(run_id) if self.reservations else None
        if owner is not None and owner.status == "active":
            if owner.owner_id != self.reservations.owner_id:
                return record
            with self.reservations.run_guard(run_id):
                return self.finalize_owned(run_id, owner)
        return self.finalize_owned(run_id, owner)

    def finalize_owned(self, run_id, owner):
        self.safety.repair_system_effects(run_id)
        from culsma_os.program_manager.models import RunFinalizationProof
        record = self.tasks.get(run_id)
        if record.body_outcome is None and record.status == "cancel_requested":
            if self.safety.effects_release_proof(run_id) is None:
                return record  # An in-flight action may still return and settle normally.
            record = self.state.begin_finalization(run_id, outcome="cancelled")
        proof = self.safety.effects_release_proof(run_id)
        if proof is None:
            return self.state.mark_reconciliation_required(run_id, "FINALIZATION_EVIDENCE_INCOMPLETE")
        if owner is not None and owner.status == "active":
            try:
                if self.conditions is not None:
                    self.conditions.finish(run_id)
            except Exception as error:
                return self.state.mark_reconciliation_required(run_id, f"PROCESSING_CONDITION_RELEASE_PENDING: {error}")
            self.settle_confirmed_attempts(run_id)
            if self.has_unsettled_permits(run_id):
                return self.state.mark_reconciliation_required(run_id, "FINALIZATION_PERMITS_UNSETTLED")
            if not self.reservations.finish(run_id):
                return self.state.mark_reconciliation_required(run_id, "FINALIZATION_RELEASE_UNCONFIRMED")
        elif owner is None and (proof["evidence_ids"] or (self.conditions and self.conditions.activations(run_id))):
            return self.state.mark_reconciliation_required(run_id, "FINALIZATION_RESERVATION_MISSING")
        # A released reservation is a durable fact, not permission to reacquire or
        # redispatch. Revalidate its evidence through the owning public boundary.
        release = self.reservations.release_confirmation(run_id) if owner is not None else None
        if owner is not None and release is None:
            return self.state.mark_reconciliation_required(run_id, "FINALIZATION_RELEASE_UNCONFIRMED")
        if owner is not None and owner.status == "released":
            self.settle_confirmed_attempts(run_id)
        if self.has_unsettled_permits(run_id):
            return self.state.mark_reconciliation_required(run_id, "FINALIZATION_PERMITS_UNSETTLED")
        verified = self.safety.release_proof(run_id)
        if verified is None:
            return self.state.mark_reconciliation_required(run_id, "FINALIZATION_EVIDENCE_INCOMPLETE")
        record = self.tasks.get(run_id)
        confirmation = RunFinalizationProof(run_id, record.revision, record.body_outcome,
            tuple(verified["evidence_ids"]), release)
        return self.state.complete_finalization(run_id, confirmation)

    def settle_confirmed_attempts(self, run_id):
        for attempt in self.evidence.attempts_for_run(run_id):
            receipt = self.evidence.find_evidence(attempt.effect_id)
            if receipt is not None:
                self.resource.settle(attempt.attempt_id, receipt)

    def has_unsettled_permits(self, run_id):
        for attempt_id in self.resource.active_attempts():
            attempt = self.evidence.find_attempt_by_id(attempt_id)
            if attempt is None or attempt.run_id == run_id:
                return True
        return False


class HostOwnershipInteractor:
    def __init__(self, lease_factory):
        self.lease_factory = lease_factory

    def embedded(self, context):
        from contextlib import contextmanager
        @contextmanager
        def guard():
            lease = self.lease_factory.build(context)
            lease.acquire()
            try:
                yield
            finally:
                lease.close()
        return guard()


class ResidentStatusInteractor:
    def __init__(self, poll_interval=0.05):
        from threading import Event, RLock
        if poll_interval <= 0:
            raise ValueError('HOST_POLL_INTERVAL_INVALID')
        self.poll_interval = poll_interval
        self.stop_requested = Event()
        self.lock = RLock()
        self.ready = False
        self.error = None
        self.blocked_run = None
        self.blocked_reason = None

    def mark_ready(self):
        with self.lock:
            self.ready = True

    def mark_failed(self, error):
        with self.lock:
            self.error = str(error) or type(error).__name__

    def note_blocked(self, run_id, reason):
        with self.lock:
            self.blocked_run, self.blocked_reason = run_id, reason

    def request_stop(self):
        self.stop_requested.set()

    def require_admission(self):
        with self.lock:
            if self.stop_requested.is_set():
                raise ValueError('HOST_STOPPING')
            if self.error:
                raise ValueError('HOST_WORKER_FAILED')
            if not self.ready:
                raise ValueError('HOST_NOT_READY')

    def snapshot(self):
        with self.lock:
            return {'status': 'failed' if self.error else 'stopping' if self.stop_requested.is_set() else 'ready' if self.ready else 'starting',
                    'worker_error': self.error, 'blocked_run': self.blocked_run, 'blocked_reason': self.blocked_reason}


class ResidentHostInteractor:
    """Own the resident lifetime; adapters never decide run admission or recovery."""
    def __init__(self, settings, status, lease: HostLeaseRepository, commands, listener, worker_factory, configuration):
        self.settings, self.status, self.lease = settings, status, lease
        self.commands, self.listener, self.worker_factory = commands, listener, worker_factory
        self.configuration = configuration

    def request_stop(self, *args):
        self.status.request_stop()

    def serve(self):
        from threading import Thread
        worker = None
        try:
            self.lease.acquire()
            self.configuration.bind(self.settings.context)
            self.listener.open()
            worker = Thread(target=self.execute_worker, name='culsma-os-execution', daemon=False)
            worker.start()
            while not self.status.stop_requested.is_set() or worker.is_alive():
                self.listener.handle_one()
        except KeyboardInterrupt:
            self.request_stop()
        finally:
            self.request_stop()
            if worker is not None:
                worker.join()
            self.listener.close()
            self.commands.close()
            self.configuration.close()
            self.lease.close()

    def execute_worker(self):
        try:
            self.configuration.verify(self.settings.context)
            self.worker_factory.build(self.settings.context, self.status).run()
        except BaseException as error:
            self.status.mark_failed(error)


class ResidentConfigurationInteractor:
    def __init__(self, repository: ResidentConfigurationRepository, connection):
        self.repository, self.connection = repository, connection
        self.fingerprint = None

    def calculate_fingerprint(self, context):
        import hashlib
        import json
        import os
        from culsma_os.resource_manager.interactors import StationPathInteractor
        station_root = StationPathInteractor().database_path(context).parent
        value = {'driver': context.driver_name,
                 'config': context.config_path.read_text() if context.config_path else None,
                 'config_path': str(context.config_path.resolve()) if context.config_path else None,
                 'station': context.station_id or os.environ.get('CULSMA_OS_STATION_ID', 'local'),
                 'station_root': str(station_root.resolve())}
        if context.workspace_config_path is not None:
            value['workspace_catalog'] = context.workspace_config_path.read_text()
            value['workspace_catalog_path'] = str(context.workspace_config_path.resolve())
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def bind(self, context):
        self.fingerprint = self.calculate_fingerprint(context)
        self.repository.bind(self.fingerprint)

    def verify(self, context):
        if self.calculate_fingerprint(context) != self.fingerprint:
            raise ValueError('HOST_CONFIGURATION_MISMATCH')

    def close(self):
        self.connection.close()


class HostLeasePathInteractor:
    def paths(self, context, socket_path=None):
        from pathlib import Path
        from culsma_os.resource_manager.interactors import StationPathInteractor
        paths = [Path(str(context.database_path.resolve()) + '.host.lock'),
                 StationPathInteractor().database_path(context).with_suffix('.host.lock')]
        if socket_path is not None:
            paths.append(Path(str(socket_path.resolve()) + '.host.lock'))
        return tuple(paths)
