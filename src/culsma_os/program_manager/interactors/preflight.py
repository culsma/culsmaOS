"""Read-only model projection before a new program's first external effect."""
from copy import deepcopy
from culsma.common.diagnostics import Diagnostic
from culsma.driver.base import DriverResult
from culsma.driver.groups import GroupDriverResult
from culsma.pipeline.plan_nodes import PlanStepTree
from culsma.runtime.executor import run
from culsma_os.driver_framework.adapters.semantic import SemanticReplayDriver
from ..models import OperationPreflightPort, ConditionPreflightPort
from .replay import ReplayEffectInteractor


class ProgramPreflightInteractor:
    def __init__(self, space, snapshot, planners: dict[str, OperationPreflightPort], max_rounds=10000, motion=None, conditions: ConditionPreflightPort | None = None):
        self.space, self.snapshot = space, deepcopy(snapshot)
        self.planners = dict(planners)
        self.max_rounds = max_rounds
        self.motion, self.conditions = motion, conditions

    def inspect(self, plan, state, scope_id):
        projection = deepcopy(state)
        data = {"plan": plan, "scope_id": scope_id, "confirmed": [], "schema": 3}
        effects = PreflightEffectInteractor(data, projection, self)
        effects.motion_projection = None
        if self.motion is not None:
            try:
                self.motion.validate_routes(plan, scope_id)
                effects.motion_projection = self.motion.positions()
            except ValueError as error:
                effects.diagnostics.append(Diagnostic("PREFLIGHT_MOTION_REJECTED", str(error), plan.span))
        result = run(plan, SemanticReplayDriver(effects), projection, max_scheduler_rounds=self.max_rounds)
        if result.ok and not effects.diagnostics and self.conditions is not None and effects.motion_projection is not None:
            try:
                effects.retained_conditions, effects.motion_projection = self.conditions.release(
                    effects.retained_conditions, effects.motion_projection)
            except ValueError as error:
                effects.diagnostics.append(Diagnostic("PREFLIGHT_CONDITION_RELEASE_REJECTED", str(error), plan.span))
        diagnostics = [*effects.diagnostics, *(d for d in result.diagnostics if d.severity == "error")]
        if not result.ok and not any(d.severity == "error" for d in diagnostics):
            diagnostics.append(Diagnostic("PREFLIGHT_PROJECTION_INCOMPLETE", "Model projection did not finish", plan.span))
        report = {
            "schema": "culsma_preflight_v1",
            "status": "rejected" if diagnostics else "passed",
            "configuration_revision": self.snapshot.configuration_revision,
            "projected_path_complete": result.ok,
            "checked_effects": effects.checked_effects,
            "diagnostics": [d.to_dict() for d in diagnostics],
            "deferred_checks": ["vendor preparation and unadvertised parameter bounds", "live readiness and consumables", "physical outcomes and non-projected paths"],
        }
        if self.snapshot.supports_transfer is None:
            report["deferred_checks"].append("legacy device has no explicit transfer capability declaration")
        return report, diagnostics

    def validate_effect(self, pending, plan, scope_id, physical_positions=None):
        step = pending.prepared.runtime_step
        planner = self.planners.get(step.op)
        if planner is None:
            raise ValueError("PREFLIGHT_OPERATION_UNSUPPORTED")
        allocations = tuple(s for protocol in plan.plans for s in PlanStepTree.leaves(protocol.steps) if s.op == "AllocContainer")
        planner.preflight(pending, self.space, self.snapshot, scope_id, allocations, physical_positions=physical_positions)


class PreflightEffectInteractor(ReplayEffectInteractor):
    """Project success in a private state; never create an execution resolution."""
    def __init__(self, data, state, preflight):
        super().__init__(data, state, None)
        self.preflight = preflight
        self.diagnostics = []
        self.checked_effects = 0
        self.retained_conditions = ()

    def validate(self, pending):
        self.checked_effects += 1
        try:
            if self.preflight.motion is not None and self.motion_projection is not None:
                allocations = tuple(s for p in self.data["plan"].plans for s in PlanStepTree.leaves(p.steps) if s.op == "AllocContainer")
                if self.preflight.conditions is not None:
                    self.retained_conditions, self.motion_projection = self.preflight.conditions.before_effect(
                        pending, self.retained_conditions, self.motion_projection)
                self.motion_projection = self.preflight.motion.validate_preflight(pending, allocations, self.motion_projection)
            self.preflight.validate_effect(pending, self.data["plan"], self.data["scope_id"],
                self.motion_projection[1] if self.motion_projection is not None else None)
            if self.preflight.conditions is not None and self.motion_projection is not None:
                self.retained_conditions = self.preflight.conditions.after_effect(
                    pending, allocations, self.retained_conditions, self.motion_projection)
        except (ValueError, NotImplementedError) as error:
            step = pending.prepared.runtime_step
            self.diagnostics.append(Diagnostic("PREFLIGHT_OPERATION_REJECTED", str(error), step.span, node_id=step.step_id))

    def execute(self, step):
        if step.op in self.bootstrap_ops:
            return DriverResult(True, "PREFLIGHT_DECLARATION", {"internal": True})
        self.validate(self.prepare_effect(step))
        return DriverResult(True, "PREFLIGHT_PROJECTED", {"projection_only": True})

    def execute_group(self, request):
        pending = self.prepare_group_effect(request)
        for member in pending.members:
            self.validate(member)
        return GroupDriverResult(request.source_member_ids,
            tuple(DriverResult(True, "PREFLIGHT_PROJECTED", {"projection_only": True}) for member in pending.members))
