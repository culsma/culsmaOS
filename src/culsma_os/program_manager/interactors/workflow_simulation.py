"""Select internal providers before admission and replay their frozen results."""
from culsma.driver.base import DriverResult
from culsma.pipeline.plan_nodes import PlanStepTree
from copy import deepcopy


class WorkflowSimulationInteractor:
    def __init__(self, simulator):
        self.simulator = simulator

    def plan(self, program, enabled):
        routes = {}
        if enabled:
            for protocol in program.plans:
                for step in PlanStepTree.leaves(protocol.steps):
                    route = self.simulator.plan_step(step)
                    if route is not None:
                        routes[step.step_id] = route
        return routes

    @staticmethod
    def routes(data):
        return data.get("workflow_simulation", {}).get("routes", {})

    @classmethod
    def execute_step(cls, data, step):
        route = cls.routes(data).get(step.step_id)
        if step.op == "img" and route is not None and route["operation"] == "img":
            return DriverResult(True, "OS_SYNTHETIC_READOUT", {
                "provider": route["provider"], "synthetic": True,
                "mode": "simulation", "result": deepcopy(route["result"])})
        return None
