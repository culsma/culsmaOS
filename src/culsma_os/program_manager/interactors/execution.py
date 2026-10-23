from ..models import SemanticHostPort
from copy import deepcopy


class ExecutionHostInteractor:

    def __init__(self, tasks, host: SemanticHostPort, state):
        self.tasks = tasks
        self.host = host
        self.state = state

    def advance(self, run_id):
        record = self.tasks.get(run_id)
        if record.status != "ready":
            return record
        if self.tasks.setup is not None:
            self.tasks.setup.require_dispatch(run_id)
        checkpoint = self.host.advance(record.checkpoint)
        data, _ = self.host.restore(checkpoint)
        if data["pending"]:
            return self.state.mark_waiting(run_id, checkpoint)
        outcome = "succeeded" if self.host.result(checkpoint).ok else "failed"
        return self.state.begin_finalization(run_id, checkpoint, outcome)

    def pending(self, run_id):
        return self.host.pending(self.tasks.get(run_id).checkpoint)

    def result(self, run_id):
        return self.host.result(self.tasks.get(run_id).checkpoint)

    def allocations(self, run_id):
        """Return completed allocation declarations from the verified existing checkpoint."""
        data, _ = self.host.restore(self.tasks.get(run_id).checkpoint)
        return tuple(
            deepcopy(step)
            for protocol in data["plan"].plans
            for step in protocol.steps
            if step.op == "AllocContainer"
            and data["state"].step_status.get(step.step_id) == "completed"
        )


    def preflight_report(self, run_id):
        return deepcopy(self.host.restore(self.tasks.get(run_id).checkpoint)[0].get("preflight"))

    def status(self, run_id):
        return self.tasks.get(run_id).status

    def plan(self, run_id):
        return deepcopy(self.host.restore(self.tasks.get(run_id).checkpoint)[0]["plan"])
