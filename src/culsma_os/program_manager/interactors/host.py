from dataclasses import replace
from culsma.common.diagnostics import Diagnostic
from ..models import RunRequest


class OSRunHostInteractor:

    def __init__(self, tasks, lifecycle, execution, material, connections, gateway, report):
        self.tasks = tasks
        self.lifecycle = lifecycle
        self.execution = execution
        self.material = material
        self.connections = connections
        self.gateway = gateway
        self.report = report

    def execute(self, plan, state):
        self.lifecycle.start_and_reconcile()
        run_id = self.tasks.submit(RunRequest(plan, state))
        self.lifecycle.run_until_settled(run_id)
        return self.result(run_id)

    def result(self, run_id):
        return self.report.result(run_id)

    def close(self):
        try:
            self.lifecycle.stop_and_reconcile()
            self.gateway.close()
        finally:
            if self.lifecycle.reservations is not None:
                self.lifecycle.reservations.close()
            for connection in self.connections:
                connection.close()


class RunReportInteractor:
    def __init__(self, tasks, execution, material, setup=None):
        self.tasks, self.execution, self.material = tasks, execution, material
        self.setup = setup

    def result(self, run_id):
        record = self.tasks.get(run_id)
        plan = self.execution.plan(run_id)
        result = self.execution.result(run_id)
        if record.status != "completed":
            result = replace(
                result,
                diagnostics=[
                    *result.diagnostics,
                    Diagnostic(
                        "OS_RUN_UNSETTLED", record.error or record.status, plan.span
                    ),
                ],
            )
            report = dict(result.user_result or {})
            report["ok"] = False
            report.setdefault("alerts", []).append(record.error or record.status)
            result = replace(result, user_result=report)
        report = dict(result.user_result or {})
        report["os"] = {
            "run_id": run_id,
            "status": record.status,
            "body_outcome": record.body_outcome,
            "body_error": record.body_error,
            "mode": "simulation",
            "unresolved_material_effects": self.material.uncertainties(run_id),
        }
        report["os"]["preflight"] = self.execution.preflight_report(run_id)
        if self.setup is not None:
            try:
                report['os']['setup'] = self.setup.get(run_id)
            except KeyError:
                if getattr(self.tasks, 'setup', None) is not None and self.tasks.setup.enabled():
                    report['os']['setup'] = {'phase': 'planning_failed', 'error': record.error}
        try:
            mode, registered_state, version = self.material.get(run_id)
            report["os"]["registered_material"] = {"mode": mode, "version": version, "state": registered_state}
        except KeyError:
            pass
        return replace(result, user_result=report)
