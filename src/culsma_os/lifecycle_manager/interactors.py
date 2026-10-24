from .repository import HostLeaseRepository, ResidentConfigurationRepository

class LifecycleInteractor:

    def __init__(
        self, tasks, runs, operations, recovery, state, device, evidence, device_id, conditions=None, finalization=None,
        *, execution_strategy
    ):
        self.tasks = tasks
        self.runs = runs
        self.operations = operations
        self.execution_strategy = execution_strategy
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
        record = self.execution_strategy.execute(run_id)
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
        self.rebuild_requested = Event()
        self.rebuild_id = None

    def request_rebuild(self, request_id):
        with self.lock:
            if self.rebuild_requested.is_set():
                raise ValueError('HOST_RECONFIGURING')
            self.ready = False
            self.error = None
            self.rebuild_id = request_id
            self.rebuild_requested.set()

    def worker_should_stop(self):
        return self.stop_requested.is_set() or self.rebuild_requested.is_set()

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
            if self.rebuild_requested.is_set():
                raise ValueError('HOST_RECONFIGURING')
            if self.error:
                raise ValueError('HOST_WORKER_FAILED')
            if not self.ready:
                raise ValueError('HOST_NOT_READY')

    def snapshot(self):
        with self.lock:
            return {'status': 'failed' if self.error else 'stopping' if self.stop_requested.is_set() else 'reconfiguring' if self.rebuild_requested.is_set() else 'ready' if self.ready else 'starting',
                    'worker_error': self.error, 'blocked_run': self.blocked_run, 'blocked_reason': self.blocked_reason}


class ResidentHostInteractor:
    """Own the resident lifetime; adapters never decide run admission or recovery."""
    def __init__(self, settings, status, lease: HostLeaseRepository, commands, listener, worker_factory, configuration, command_factory=None):
        self.settings, self.status, self.lease = settings, status, lease
        self.commands, self.listener, self.worker_factory = commands, listener, worker_factory
        self.configuration, self.command_factory = configuration, command_factory

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
                if self.status.rebuild_requested.is_set() and not worker.is_alive() and not self.status.stop_requested.is_set():
                    if self.rebuild_worker():
                        worker = Thread(target=self.execute_worker,name='culsma-os-execution',daemon=False)
                        worker.start()
                self.configuration.observe(self.status)
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

    def rebuild_worker(self):
        from dataclasses import replace
        request_id = self.status.rebuild_id
        if self.status.snapshot()['worker_error']:
            self.configuration.fail_rebuild(request_id)
            self.status.rebuild_requested.clear()
            return False
        try:
            context = self.configuration.apply(request_id,self.settings.context)
            self.settings = replace(self.settings,context=context)
            commands = self.command_factory.build(context,self.status,self.configuration)
        except Exception as error:
            self.configuration.fail_rebuild(request_id)
            self.status.rebuild_requested.clear()
            self.status.mark_failed(error)
            return False
        self.commands.close()
        self.commands, self.listener.commands = commands, commands
        self.status.rebuild_requested.clear()
        return True

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
        self.base_fingerprint = None
        self.in_flight = None
        self.repository.initialize_activation()

    def restore(self, context):
        from dataclasses import replace
        from pathlib import Path
        active = self.repository.active()
        self.base_fingerprint = self.calculate_fingerprint(context)
        if active is None:
            return context
        if self.base_fingerprint not in {active['base_fingerprint'],active['fingerprint']}:
            raise ValueError('HOST_CONFIGURATION_MISMATCH')
        self.base_fingerprint = active['base_fingerprint']
        restored = replace(context,config_path=Path(active['config_path']))
        if self.calculate_fingerprint(restored) != active['fingerprint']:
            raise ValueError('HOST_CONFIGURATION_SNAPSHOT_CHANGED')
        return restored

    def describe(self, status, request_id=None):
        active = self.repository.active()
        return {'host':status.snapshot(),'active':{
            'fingerprint':self.fingerprint,
            'origin':({key:active[key] for key in ['draft_id','revision','title','configuration_fingerprint']} if active else None)},
            'receipt':self.public_receipt(self.repository.receipt(request_id))}

    def public_receipt(self, receipt):
        if receipt is None:
            return None
        return {key:receipt.get(key) for key in ['request_id','status','error','draft_id','revision','title','configuration_fingerprint']}

    def previous_request(self, request, context):
        import hashlib
        import json
        body = {'configuration':request.configuration,'origin':request.configuration_origin,
                'expected':request.configuration_fingerprint,'driver':request.driver}
        try:
            fingerprint = hashlib.sha256(json.dumps(body,sort_keys=True,allow_nan=False).encode()).hexdigest()
        except (ValueError,TypeError):
            raise ValueError('HOST_CONFIGURATION_INVALID') from None
        if not isinstance(request.request_id,str) or not request.request_id:
            raise ValueError('HOST_CONFIGURATION_INVALID')
        origin = request.configuration_origin
        if (not isinstance(request.configuration,dict) or not isinstance(origin,dict)
                or set(origin) != {'draft_id','revision','fingerprint','title'}
                or type(origin['revision']) is not int or origin['revision'] < 1
                or any(not isinstance(origin[key],str) or not origin[key] for key in ['draft_id','fingerprint','title'])):
            raise ValueError('HOST_CONFIGURATION_INVALID')
        encoded = json.dumps(request.configuration,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        if len(encoded)>200000 or hashlib.sha256(encoded).hexdigest()!=origin['fingerprint']:
            raise ValueError('HOST_CONFIGURATION_INVALID')
        previous = self.repository.receipt(request.request_id)
        if previous is not None and previous['request_fingerprint'] != fingerprint:
            raise ValueError('HOST_CONFIGURATION_REQUEST_CONFLICT')
        return previous,fingerprint

    def request(self, request, context, status):
        import re
        if (not isinstance(request.request_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request.request_id) is None
                or not isinstance(request.configuration,dict) or not isinstance(request.configuration_origin,dict)
                or set(request.configuration_origin) != {'draft_id','revision','fingerprint','title'}):
            raise ValueError('HOST_CONFIGURATION_INVALID')
        previous,fingerprint = self.previous_request(request,context)
        if previous is not None:
            return self.public_receipt(previous)
        if request.driver != context.driver_name:
            raise ValueError('HOST_CONFIGURATION_DRIVER_CHANGE_UNSUPPORTED')
        if request.configuration_fingerprint != self.fingerprint:
            raise ValueError('HOST_CONFIGURATION_STALE')
        path = self.repository.snapshot(context.database_path.parent/'configurations',request.configuration)
        origin = request.configuration_origin
        record = {'config_path':str(path.resolve()),'base_fingerprint':self.base_fingerprint or self.fingerprint,
                  'expected_fingerprint':self.fingerprint,'driver':request.driver,'draft_id':origin['draft_id'],
                  'revision':origin['revision'],'title':origin['title'],'configuration_fingerprint':origin['fingerprint']}
        result = self.repository.prepare(request.request_id,fingerprint,record)
        status.request_rebuild(request.request_id)
        return self.public_receipt(result)

    def apply(self, request_id, context):
        from dataclasses import replace
        from pathlib import Path
        record = self.repository.receipt(request_id)
        target = replace(context,config_path=Path(record['config_path']))
        active = {key:record[key] for key in ['config_path','base_fingerprint','driver','draft_id','revision','title','configuration_fingerprint']}
        active['fingerprint'] = self.calculate_fingerprint(target)
        self.repository.activate(request_id,active,record['expected_fingerprint'])
        self.fingerprint = active['fingerprint']
        self.in_flight = request_id
        return target

    def fail_rebuild(self, request_id):
        self.repository.settle(request_id,'failed','HOST_CONFIGURATION_START_FAILED')
        self.in_flight = None

    def observe(self, status):
        if self.in_flight is None:
            return
        state = status.snapshot()
        if state['status'] in {'ready','failed'}:
            self.repository.settle(self.in_flight,'applied' if state['status']=='ready' else 'failed',
                                   None if state['status']=='ready' else 'HOST_CONFIGURATION_START_FAILED')
            self.in_flight = None

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
        self.repository.interrupt_pending()

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


from culsma_os.auth.interactors import AuthorizedInteractor


class ConsoleActivationInteractor(AuthorizedInteractor):
    required_capability = 'configuration:activate'

    def __init__(self, tokens, drafts, resident):
        super().__init__(tokens)
        self.drafts, self.resident = drafts, resident

    def perform(self, request):
        import re
        from .models import ConsoleActivationRequest
        from culsma_os.workspace_manager.models import ConfigurationError
        if not isinstance(request,ConsoleActivationRequest):
            raise ConfigurationError('CONFIGURATION_ACTIVATION_REQUEST_INVALID')
        if request.action == 'status':
            if any(value is not None for value in [request.draft_id,request.revision,request.expected_fingerprint]):
                raise ConfigurationError('CONFIGURATION_ACTIVATION_REQUEST_INVALID')
            payload = {'action':'configuration-status'}
            if request.request_id is not None:
                if not isinstance(request.request_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request.request_id) is None:
                    raise ConfigurationError('CONFIGURATION_ACTIVATION_REQUEST_INVALID')
                payload['request_id'] = request.request_id
                payload['action'] = 'activation-status'
        elif request.action == 'apply':
            if (not isinstance(request.request_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request.request_id) is None
                    or not isinstance(request.expected_fingerprint,str) or re.fullmatch(r'[a-f0-9]{64}',request.expected_fingerprint) is None):
                raise ConfigurationError('CONFIGURATION_ACTIVATION_REQUEST_INVALID')
            draft = self.drafts.validated(request.draft_id,request.revision)
            payload = {'action':'configure','request_id':request.request_id,'configuration_fingerprint':request.expected_fingerprint,
                       'configuration':draft['configuration'],'driver':draft['driver'],
                       'configuration_origin':{key:draft[key] for key in ['draft_id','revision','fingerprint','title']}}
        else:
            raise ConfigurationError('CONFIGURATION_ACTIVATION_REQUEST_INVALID')
        try:
            result = self.resident.execute(payload)
        except OSError as error:
            raise ConfigurationError('CONFIGURATION_HOST_RESPONSE_UNAVAILABLE','unavailable') from error
        except ValueError as error:
            code = str(error)
            if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) is None:
                code = 'CONFIGURATION_HOST_REJECTED'
            raise ConfigurationError(code,'conflict') from error
        if not isinstance(result,dict):
            raise ConfigurationError('CONFIGURATION_HOST_RESPONSE_INVALID','bad_response')
        return result
