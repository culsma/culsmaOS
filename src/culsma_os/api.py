"""Thin local adapter; business decisions stay in Interactors."""

from culsma_os.program_manager.models import RunRequest


class CulsmaOSClient:

    def __init__(self, tasks, lifecycle, execution, report):
        self.tasks = tasks
        self.lifecycle = lifecycle
        self.execution = execution
        self.report = report

    def start(self):
        return self.lifecycle.start_and_reconcile()

    def submit_run(self, request: RunRequest):
        return self.tasks.submit(request)

    def setup_plan(self, run_id):
        return self.tasks.setup.get(run_id)

    def revise_setup(self, run_id, preferences):
        return self.tasks.setup.plan(run_id, preferences)

    def begin_setup(self, run_id, fingerprint):
        return self.tasks.setup.begin_loading(run_id, fingerprint)

    def confirm_setup(self, run_id, fingerprint, acknowledged=False, source='operator_attestation'):
        return self.tasks.setup.confirm(run_id, fingerprint, acknowledged, source)

    def get_run(self, run_id):
        return self.tasks.get(run_id)

    def advance_run(self, run_id):
        return self.lifecycle.advance_once(run_id)

    def run_until_settled(self, run_id):
        return self.lifecycle.run_until_settled(run_id)

    def result(self, run_id):
        return self.report.result(run_id)

    def pause_run(self, run_id):
        return self.lifecycle.pause_run(run_id)

    def take_over_run(self, run_id):
        return self.lifecycle.take_over_run(run_id)

    def resume_run(self, run_id):
        return self.lifecycle.resume_run(run_id)

    def cancel_run(self, run_id):
        return self.lifecycle.cancel_run(run_id)

    def close(self):
        self.lifecycle.stop_and_reconcile()


class OSApplication:

    def __init__(self, host, client):
        self.host = host
        self.client = client

    def execute(self, plan, state):
        return self.host.execute(plan, state)

    def close(self):
        self.host.close()
