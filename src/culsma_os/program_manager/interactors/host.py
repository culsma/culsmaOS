from dataclasses import replace
from culsma.common.diagnostics import Diagnostic
from culsma.pipeline.plan_nodes import PlanStepTree
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
    def __init__(self, tasks, execution, material, setup=None, evidence=None, fault_reader=None):
        self.tasks, self.execution, self.material = tasks, execution, material
        self.setup = setup
        self.evidence = evidence
        self.fault_reader = fault_reader

    def execution_mode(self, mode):
        """Only a persisted run mode identifies simulation versus hardware."""
        return mode if mode in ('simulation', 'physical') else 'unknown'

    def receipt_faults(self, run_id):
        if self.fault_reader is not None:
            return self.fault_reader(run_id)
        if self.evidence is None:
            return []
        faults = []
        for attempt in self.evidence.attempts_for_run(run_id):
            receipt = self.evidence.find_evidence(attempt.effect_id)
            if receipt is None or receipt.outcome == "completed":
                continue
            if (receipt.run_id, receipt.attempt_id, receipt.effect_id, receipt.mode) != (
                    run_id, attempt.attempt_id, attempt.effect_id, attempt.mode):
                continue
            faults.extend((attempt, fault) for fault in receipt.payload.get("faults", ()))
        return faults

    def fault_diagnostics(self, plan, receipt_faults):
        steps = {step.step_id: step for protocol in plan.plans for step in PlanStepTree.walk(protocol.steps)}
        diagnostics = []
        for attempt, fault in receipt_faults:
            if not isinstance(fault, dict) or fault.get("reason") != "culsma.operation.completion_unconfirmed":
                continue
            operation_id = attempt.context.get("step_id")
            step = steps.get(operation_id)
            if step is None and isinstance(operation_id, str):
                parent_id, marker, ordinal = operation_id.rpartition("/motion/")
                if marker and ordinal.isdecimal():
                    step = steps.get(parent_id)
            details = fault.get("native_details")
            details = details if isinstance(details, dict) else {}
            kind = details.get("operation_kind")
            operation = kind.replace("_", " ") if isinstance(kind, str) and kind else "device operation"
            context = fault.get("context")
            context = context if isinstance(context, dict) else {}
            device = " / ".join(value for value in (context.get("device"), context.get("module")) if isinstance(value, str) and value)
            location = f" on {device}" if device else ""
            message = f"Completion is not confirmed for {operation}{location}."
            original = details.get("message")
            if isinstance(original, str) and original:
                exception_type = details.get("exception_type")
                prefix = f"{exception_type}: " if isinstance(exception_type, str) and exception_type else ""
                message += f" {prefix}{original}"
            diagnostic = Diagnostic(
                "OS_DEVICE_OPERATION_UNCONFIRMED", message, step.span if step else None,
                node_id=step.step_id if step else operation_id,
            )
            if diagnostic not in diagnostics:
                diagnostics.append(diagnostic)
        return diagnostics

    def result(self, run_id):
        record = self.tasks.get(run_id)
        plan = self.execution.plan(run_id)
        result = self.execution.result(run_id)
        receipt_faults = self.receipt_faults(run_id) if record.status != "completed" else []
        faults = list(record.faults)
        for _, fault in receipt_faults:
            if fault not in faults:
                faults.append(fault)
        report = dict(result.user_result or {})
        if record.status != "completed":
            diagnostics = self.fault_diagnostics(plan, receipt_faults)
            if diagnostics:
                report["diagnostics"] = [d.to_dict() for d in diagnostics]
                alerts = [f"{d.code}: {d.message}" for d in diagnostics]
            else:
                diagnostics = [Diagnostic("OS_RUN_UNSETTLED", record.error or record.status, plan.span)]
                alerts = [record.error or record.status]
            report["ok"] = False
            report["alerts"] = [*report.get("alerts", ()), *alerts]
            result = replace(
                result,
                diagnostics=[*result.diagnostics, *diagnostics],
            )
        report["os"] = {
            "run_id": run_id,
            "status": record.status,
            "body_outcome": record.body_outcome,
            "body_error": record.body_error,
            "faults": faults,
            "mode": "unknown",
            "unresolved_material_effects": self.material.uncertainties(run_id),
        }
        report["os"]["preflight"] = self.execution.preflight_report(run_id)
        workflow = self.execution.workflow_simulation_report(run_id)
        if workflow is not None:
            report["os"]["workflow_simulation"] = workflow
            report["os"]["mode"] = "simulation"
        if self.setup is not None:
            try:
                report['os']['setup'] = self.setup.get(run_id)
            except KeyError:
                if getattr(self.tasks, 'setup', None) is not None and self.tasks.setup.enabled():
                    report['os']['setup'] = {'phase': 'planning_failed', 'error': record.error}
        try:
            mode, registered_state, version = self.material.get(run_id)
            report["os"]["mode"] = self.execution_mode(mode)
            report["os"]["registered_material"] = {"mode": mode, "version": version, "state": registered_state}
        except KeyError:
            pass
        return replace(result, user_result=report)
