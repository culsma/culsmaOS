"""Resident admission, inspection and execution share the existing OS Interactors."""
from uuid import uuid4
from ..models import QueueSubmission, ResidentAdmissionError, RunRequest, RunControlRequest
from culsma_os.resource_manager.models import ResourceConflict
from ..repositories.queue import RunQueueRepository


class ResidentCommandInteractor:
    def __init__(self, compilation, tasks, queue: RunQueueRepository, inspector, semantics, codec, status, context, devices, configuration=None, setup_requests=None):
        self.compilation, self.tasks, self.queue = compilation, tasks, queue
        self.inspector, self.semantics, self.codec = inspector, semantics, codec
        self.status, self.context, self.devices, self.configuration = status, context, devices, configuration
        self.setup_requests = setup_requests

    def execute(self, request):
        if request.action.startswith('setup-'):
            self.require_run(request.run_id)
            return self.setup_requests.execute(request)
        if request.action in {'configuration-status','activation-status'}:
            return self.configuration.describe(self.status,request.request_id if request.action=='activation-status' else None)
        if request.action == 'configure':
            previous,_ = self.configuration.previous_request(request,self.context)
            if previous is not None:
                return self.configuration.public_receipt(previous)
            self.require_idle_configuration()
            return self.configuration.request(request,self.context,self.status)
        if request.action == 'host-status':
            return self.status.snapshot()
        if request.action == 'device-status':
            return self.devices.execute()
        if request.action == 'shutdown':
            self.status.request_stop()
            return {'accepted': True, 'status': 'stopping'}
        if request.action == 'runs':
            return {'runs': [self.describe(entry.run_id) for entry in self.queue.entries()]}
        if request.action == 'run-evidence':
            self.require_run(request.run_id)
            return self.inspector.execute(RunControlRequest('evidence', request.run_id, self.context))
        if request.action == 'status':
            self.require_run(request.run_id)
            result = self.inspector.execute(RunControlRequest('status', request.run_id, self.context))
            result['pending_controls'] = list(self.queue.pending_controls(request.run_id))
            return result
        if request.action == 'control-status':
            self.require_run(request.run_id)
            try:
                command = self.queue.control(request.request_id)
            except KeyError as error:
                raise ValueError('HOST_CONTROL_NOT_FOUND') from error
            if command['run_id'] != request.run_id:
                raise ValueError('HOST_CONTROL_NOT_FOUND')
            return command
        self.status.require_admission()
        if request.action == 'submit':
            return self.submit(request)
        if request.action in {'pause', 'resume', 'cancel'}:
            self.require_run(request.run_id)
            return self.queue.add_control(request.request_id or str(uuid4()), request.run_id, request.action)
        raise ValueError('HOST_COMMAND_UNSUPPORTED')

    def require_idle_configuration(self):
        state = self.status.snapshot()
        if state['status'] not in {'ready','failed'}:
            raise ValueError('HOST_RECONFIGURING' if state['status']=='reconfiguring' else 'HOST_NOT_READY')
        if self.queue.head() is not None or self.queue.pending_controls():
            raise ValueError('HOST_CONFIGURATION_BUSY')
        report = self.devices.execute()
        resources = report['resources']
        if (resources.get('local_accounting') != 'recorded' or resources.get('station_accounting') != 'recorded'
                or any(resources.get(key) for key in ['locks','permits','station_reservations','station_locks'])
                or any(device['unresolved_operations'] or device['positions']['status']=='unknown' for device in report['devices'])):
            raise ValueError('HOST_CONFIGURATION_RESOURCES_UNRESOLVED')

    def require_run(self, run_id):
        if not run_id or not self.queue.contains(run_id):
            raise ValueError('HOST_RUN_NOT_FOUND')

    def describe(self, run_id):
        record = self.tasks.get(run_id)
        return {key: getattr(record, key) for key in ('run_id', 'status', 'revision', 'error', 'body_outcome', 'body_error')}

    def submit(self, request):
        if request.source is None:
            raise ValueError('HOST_SOURCE_REQUIRED')
        compiled = self.compilation.compile([request.source], request.material_state, request.library_roots)
        diagnostics = [*compiled.semantic.diagnostics, *compiled.typed.diagnostics, *compiled.plan.diagnostics]
        errors = [d for d in diagnostics if d.severity == 'error']
        if errors:
            raise ResidentAdmissionError('PROGRAM_DIAGNOSTICS_REJECTED', (d.to_dict() for d in errors))
        errors = [d for d in self.semantics.validate_plan(compiled.plan) if d.severity == 'error']
        if errors:
            raise ResidentAdmissionError('HOST_PLAN_UNSUPPORTED', (d.to_dict() for d in errors))
        identity = ((compiled.plan,compiled.state,request.configuration_fingerprint) if request.configuration_fingerprint is not None
                    else (compiled.plan,compiled.state))
        submission = QueueSubmission(request.request_id or str(uuid4()),
            self.codec.fingerprint(identity), str(request.source.resolve()))
        previous = self.queue.submission(submission.request_id)
        if previous is not None:
            if previous.fingerprint != submission.fingerprint or previous.source != submission.source:
                raise ValueError('HOST_SUBMISSION_ID_CONFLICT')
            return {**self.describe(previous.run_id), 'request_id': previous.request_id, 'accepted': True}
        if request.configuration_fingerprint is not None and request.configuration_fingerprint != self.configuration.fingerprint:
            raise ValueError('HOST_CONFIGURATION_STALE')
        run_id = self.tasks.submit(RunRequest(compiled.plan, compiled.state), submission)
        return {**self.describe(run_id), 'request_id': submission.request_id, 'accepted': True}

    def close(self):
        self.inspector.close()


class ResidentWorkerInteractor:
    def __init__(self, application, queue: RunQueueRepository, connection, status):
        self.application, self.queue, self.connection, self.status = application, queue, connection, status
        self.admitted = set()

    def run(self):
        try:
            self.application.client.start()
            self.status.mark_ready()
            while not self.status.worker_should_stop():
                self.tick()
                self.status.stop_requested.wait(self.status.poll_interval)
            head = self.queue.head()
            if head is not None and head.run_id in self.admitted:
                self.application.client.pause_run(head.run_id)
        finally:
            try:
                self.application.close()
            finally:
                self.connection.close()

    def process_controls(self):
        for command in self.queue.pending_controls():
            run_id, action = command['run_id'], command['action']
            try:
                if action == 'resume':
                    head = self.queue.head()
                    if (head is not None and head.run_id == run_id
                            and self.application.client.get_run(run_id).status != 'awaiting_setup'):
                        self.ensure_owned(run_id)
                    self.application.client.resume_run(run_id)
                elif action == 'pause':
                    self.application.client.pause_run(run_id)
                elif action == 'cancel':
                    self.application.client.cancel_run(run_id)
                else:
                    raise ValueError('HOST_CONTROL_UNSUPPORTED')
            except (ValueError, ResourceConflict) as error:
                self.queue.settle_control(command['request_id'], str(error))
            else:
                self.queue.settle_control(command['request_id'])

    def ensure_owned(self, run_id):
        if run_id not in self.admitted:
            self.application.client.take_over_run(run_id)
            self.admitted.add(run_id)

    def tick(self):
        setup = self.application.client.tasks.setup
        if setup is not None:
            setup.process_requests()
        self.process_controls()
        if self.status.worker_should_stop():
            return
        head = self.queue.head()
        if head is None:
            self.status.note_blocked(None, None)
            return
        record = self.application.client.get_run(head.run_id)
        if setup is not None and setup.enabled():
            try:
                setup.get(head.run_id)
            except KeyError:
                try:
                    setup.plan(head.run_id)
                except ValueError as error:
                    self.status.note_blocked(head.run_id, str(error))
                    return
            record = self.application.client.get_run(head.run_id)
            if record.status == 'awaiting_setup':
                self.status.note_blocked(head.run_id, record.error or 'awaiting_setup')
                return
        if record.status == 'paused':
            self.status.note_blocked(head.run_id, 'paused')
            return
        try:
            self.ensure_owned(head.run_id)
            record = self.application.client.advance_run(head.run_id)
        except ResourceConflict as error:
            self.status.note_blocked(head.run_id, str(error))
            return
        self.status.note_blocked(head.run_id if record.status in {'paused','needs_reconciliation'} else None,
                                 record.error or record.status if record.status in {'paused','needs_reconciliation'} else None)
