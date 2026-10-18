from uuid import uuid4
from ..models import RunRequest
from ..repositories.runs import TaskRepository


class TaskInteractor:
    def __init__(self, repository: TaskRepository, preparation, state):
        self.repository, self.preparation, self.state = repository, preparation, state

    def submit(self, request: RunRequest, queue_submission=None) -> str:
        run_id = str(uuid4())
        checkpoint = self.preparation.prepare(request, run_id)
        self.state.create_run(run_id, checkpoint, queue_submission)
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
