from uuid import uuid4
from dataclasses import replace
from ..models import RunRequest
from ..repositories.runs import TaskRepository


class TaskInteractor:
    def __init__(self, repository: TaskRepository, preparation, state):
        self.repository, self.preparation, self.state = repository, preparation, state
        self.setup = None
        self.profile_bindings = None

    def submit(self, request: RunRequest, queue_submission=None) -> str:
        run_id = str(uuid4())
        checkpoint = self.prepare_checkpoint(request, run_id)
        if request.profile_bindings is not None:
            if self.profile_bindings is None: raise ValueError('INSTRUMENT_PROFILES_UNSUPPORTED')
            self.profile_bindings.bind_run(run_id, request.profile_bindings)
        return self.admit_checkpoint(run_id, checkpoint, queue_submission, request.setup_preferences)

    def prepare_checkpoint(self, request, run_id):
        return self.preparation.prepare(request, run_id)

    def submit_simulation_continuation(self, run_id, checkpoint, station):
        return self.admit_checkpoint(run_id, checkpoint, simulation_station=station)

    def admit_checkpoint(self, run_id, checkpoint, queue_submission=None, setup_preferences=None, *, simulation_station=None):
        required = self.setup is not None and self.setup.enabled()
        self.state.create_run(run_id, checkpoint, queue_submission, setup_required=required,
            simulation_station=simulation_station)
        if required:
            try:
                self.setup.plan(run_id, setup_preferences)
            except ValueError as error:
                # Persist a blocked preparation, never a ready run without a valid plan.
                self.repository.save(replace(self.state.get(run_id), error=str(error)))
        return run_id

    def get(self, run_id):
        return self.state.get(run_id)

    def unfinished(self):
        return tuple(self.state.get(record.run_id) for record in self.repository.unfinished())

    def pause_dispatch(self, run_id):
        return self.state.pause_dispatch(run_id)

    def resume_dispatch(self, run_id):
        return self.state.resume_dispatch(run_id)

    def request_cancel(self, run_id):
        return self.state.request_cancel(run_id)

    def note_blocked(self, run_id, reason):
        return self.state.note_blocked(run_id, reason)

    def pending_events(self):
        return self.repository.pending_events()

    def mark_published(self, event_id):
        self.repository.mark_published(event_id)
