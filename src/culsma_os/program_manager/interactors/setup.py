"""Own preparation, operator attestation and a dispatch gate over the original runner."""
from copy import deepcopy
from datetime import datetime, timezone
from .workspace import WorkspaceCheckpointInteractor


class RunSetupInteractor:
    def __init__(self, repository, tasks, state, host, codec, requirements, planner, catalogue, snapshot, reservations, evidence, workspaces, device):
        self.repository, self.tasks, self.state, self.host = repository, tasks, state, host
        self.codec, self.requirements, self.planner = codec, requirements, planner
        self.catalogue, self.snapshot = deepcopy(catalogue), snapshot
        self.reservations, self.evidence = reservations, evidence
        self.workspaces, self.device = workspaces, device

    def enabled(self):
        return self.snapshot.setup_required

    def get(self, run_id):
        return self.repository.get(run_id)

    def plan(self, run_id, preferences=None):
        with self.reservations.station_guard():
            record = self.tasks.get(run_id)
            if (record.body_outcome is not None or record.status not in {'awaiting_setup', 'ready'}
                    or self.evidence.attempts_for_run(run_id)):
                raise ValueError('SETUP_EXECUTION_ALREADY_STARTED')
            data = self.codec.loads(record.checkpoint)
            if data['confirmed'] or data['pending'] is not None:
                raise ValueError('SETUP_EXECUTION_ALREADY_STARTED')
            try:
                previous = self.get(run_id)
            except KeyError:
                previous = {'revision': 0, 'phase': 'planned'}
            result = self.planner.plan(self.requirements.inspect(record.checkpoint), self.catalogue, preferences)
            identity = {'plan': data['plan_fingerprint'], 'initial': data['initial_fingerprint'],
                        'configuration': self.snapshot.configuration_revision, 'catalogue': self.codec.fingerprint(self.catalogue)}
            document = {'schema': 'culsma_run_setup_v1', 'run_id': run_id, 'identity': identity,
                        'preferences': deepcopy(preferences or {}), **result}
            workspace = {'schema': 'culsma_run_workspace_v1', 'id': 'setup-' + run_id,
                         'plan_fingerprint': data['plan_fingerprint'], 'bindings': result['bindings'], 'routes': {}}
            checkpoint = self.host.create(data['plan'], data['initial_state'], run_id)
            checkpoint = WorkspaceCheckpointInteractor(self.codec).attach(checkpoint, workspace)
            self.state.replace_setup(run_id, checkpoint)
            self.workspaces.invalidate(run_id)
            projected = self.codec.loads(self.host.advance(checkpoint))
            if any(d.severity == 'error' for d in projected['diagnostics']):
                raise ValueError('SETUP_PREFLIGHT_REJECTED')
            document['preflight'] = deepcopy(projected.get('preflight'))
            document['fingerprint'] = self.codec.fingerprint(document)
            document.update(phase='loading' if previous['phase'] in {'loading', 'confirmed'} else 'planned', confirmation=None)
            return self.repository.save(run_id, document, previous['revision'])

    def validate(self, run_id, fingerprint):
        value = self.get(run_id)
        data = self.codec.loads(self.tasks.get(run_id).checkpoint)
        identity = {'plan': data['plan_fingerprint'], 'initial': data['initial_fingerprint'],
                    'configuration': self.snapshot.configuration_revision, 'catalogue': self.codec.fingerprint(self.catalogue)}
        if (value['fingerprint'] != fingerprint or value['identity'] != identity
                or data.get('workspace', {}).get('bindings') != value['bindings']):
            raise ValueError('SETUP_PLAN_STALE')
        payload = {k: v for k, v in value.items() if k not in {'revision', 'fingerprint', 'phase', 'confirmation'}}
        if self.codec.fingerprint(payload) != fingerprint:
            raise ValueError('SETUP_PLAN_INVALID')
        return value

    def begin_loading(self, run_id, fingerprint):
        with self.reservations.station_guard():
            value = self.validate(run_id, fingerprint)
            if self.tasks.get(run_id).status != 'awaiting_setup':
                raise ValueError('SETUP_STATE_INVALID')
            self.reservations.acquire(run_id)
            with self.reservations.run_guard(run_id) as reservation:
                self.device.admit_session(allow_reconfiguration=reservation.generation == 1)
                if value['phase'] == 'loading':
                    return value
                value.update(phase='loading', confirmation=None)
                return self.repository.save(run_id, value, value['revision'])

    def confirm(self, run_id, fingerprint, acknowledged=False, source='operator_attestation'):
        if acknowledged is not True or source not in {'operator_attestation', 'simulation_fixture'}:
            raise ValueError('SETUP_EXPLICIT_CONFIRMATION_REQUIRED')
        if source == 'simulation_fixture' and self.snapshot.mode != 'simulation':
            raise ValueError('SETUP_CONFIRMATION_MODE_INVALID')
        with self.reservations.run_guard(run_id) as reservation:
            value = self.validate(run_id, fingerprint)
            if self.tasks.get(run_id).status not in {'awaiting_setup', 'ready'}:
                raise ValueError('SETUP_STATE_INVALID')
            if value['phase'] == 'confirmed':
                self.require_dispatch(run_id)
                self.state.confirm_setup(run_id)
                return value
            if value['phase'] != 'loading':
                raise ValueError('SETUP_LOADING_NOT_STARTED')
            value.update(phase='confirmed', confirmation={'source': source, 'physical_observation': False,
                'fingerprint': fingerprint, 'reservation_generation': reservation.generation,
                'run_store': reservation.run_store, 'resources': list(reservation.resources),
                'recorded_at': datetime.now(timezone.utc).isoformat()})
            result = self.repository.save(run_id, value, value['revision'])
            self.state.confirm_setup(run_id)
            return result

    def require_dispatch(self, run_id):
        if not self.enabled():
            return
        value = self.get(run_id)
        self.validate(run_id, value['fingerprint'])
        confirmation = value.get('confirmation')
        reservation = self.reservations.owned(run_id)
        if (value['phase'] != 'confirmed' or not confirmation
                or confirmation['fingerprint'] != value['fingerprint']
                or confirmation['run_store'] != reservation.run_store
                or confirmation['resources'] != list(reservation.resources)):
            raise ValueError('SETUP_CONFIRMATION_REQUIRED')

    def process_requests(self):
        for request in self.repository.pending_requests():
            try:
                if not self.enabled():
                    raise ValueError('SETUP_DEVICE_UNSUPPORTED')
                run_id = request['run_id']
                if request['action'] == 'revise':
                    with self.reservations.station_guard():
                        if request.get('fingerprint') is not None:
                            self.validate(run_id, request['fingerprint'])
                        result = self.plan(run_id, request.get('preferences'))
                elif request['action'] == 'begin':
                    result = self.begin_loading(run_id, request['fingerprint'])
                else:
                    result = self.confirm(run_id, request['fingerprint'], request.get('acknowledged', False))
            except (ValueError, KeyError) as error:
                self.repository.settle_request(request['request_id'], error=str(error))
            else:
                self.repository.settle_request(request['request_id'], result=result)


class RunSetupRequestInteractor:
    def __init__(self, repository, tasks):
        self.repository, self.tasks = repository, tasks

    def execute(self, request):
        from uuid import uuid4
        self.tasks.get(request.run_id)
        action = request.action.removeprefix('setup-')
        if action == 'show':
            return {**self.repository.get(request.run_id), 'activity': self.repository.activity(request.run_id)}
        if action == 'status':
            result = self.repository.request(request.request_id)
            if result['run_id'] != request.run_id:
                raise ValueError('SETUP_REQUEST_NOT_FOUND')
            return result
        if action not in {'revise', 'begin', 'confirm'}:
            raise ValueError('SETUP_COMMAND_INVALID')
        if action == 'confirm' and request.setup_acknowledged is not True:
            raise ValueError('SETUP_EXPLICIT_CONFIRMATION_REQUIRED')
        if action in {'begin', 'confirm'} and (not isinstance(request.setup_fingerprint, str) or len(request.setup_fingerprint) != 64):
            raise ValueError('SETUP_PLAN_STALE')
        return self.repository.enqueue(request.request_id or str(uuid4()),
            {'run_id':request.run_id, 'action':action, 'fingerprint':request.setup_fingerprint,
             'preferences':request.setup_preferences, 'acknowledged':request.setup_acknowledged,
             'origin':request.setup_origin or 'local-cli'})


class RunSetupInspectionInteractor:
    def __init__(self, repository):
        self.repository = repository

    def get(self, run_id):
        return self.repository.get(run_id)
