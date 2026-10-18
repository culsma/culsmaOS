"""Run-owned retained conditions and separately journaled OS release effects."""
from uuid import uuid4
from ..models import MagneticReleaseIntent
from culsma_os.workspace_manager.models import ResolvedContainerRef
from culsma_os.driver_framework.models import PlanContext


class ProcessingConditionInteractor:
    def __init__(self, evidence, gateway, resource, motions=None):
        self.evidence, self.gateway, self.resource = evidence, gateway, resource
        self.motions = motions

    def activations(self, run_id):
        return tuple(a for a in self.evidence.attempts_for_run(run_id)
                     if a.context.get("description", {}).get("retained_condition", {}).get("kind") == "magnetic_field")

    def release_id(self, activation):
        return f"{activation.effect_id}/condition-release"

    def release_completed(self, activation):
        attempt = self.evidence.find_attempt(self.release_id(activation))
        fact = self.evidence.find_evidence(self.release_id(activation))
        condition = activation.context["description"]["retained_condition"]
        passive = condition.get("release_kind") == "remove_labware"
        if passive and (self.motions is None or not self.motions.condition_release_registered(activation)):
            return False
        phases = {"verify_removed": "returned"} if passive else {"disengage": "returned"}
        return (attempt is not None and fact is not None and fact.run_id == activation.run_id and fact.mode == activation.mode
                and fact.attempt_id == attempt.attempt_id
                and attempt.context["configuration_revision"] == activation.context["configuration_revision"]
                and fact.outcome == "completed" and fact.payload.get("operation_kind") == "magnetic_release"
                and fact.payload.get("module_id") == activation.context["description"]["module_id"]
                and fact.payload.get("request", {}).get("producer_step_id") == activation.context["step_id"]
                and fact.payload.get("phases") == phases)

    def outstanding(self, run_id):
        return tuple(a for a in self.activations(run_id) if not self.release_completed(a))

    def is_release_attempt(self, attempt):
        return any(self.release_id(a) == attempt.effect_id for a in self.activations(attempt.run_id))

    def before_effect(self, run_id, pending):
        if not self.activations(run_id) or self.evidence.find_attempt(pending.effect_id) is not None:
            return True
        from .preparation import MagneticEnvironmentInteractor
        if not MagneticEnvironmentInteractor().retains(pending):
            # Completed releases are settled idempotently, including crash recovery.
            self.finish(run_id)
        return True

    def finish(self, run_id):
        for activation in self.activations(run_id):
            release_id = self.release_id(activation)
            attempted = self.evidence.find_attempt(release_id)
            if self.release_completed(activation):
                self.resource.settle(attempted.attempt_id, self.evidence.find_evidence(release_id))
                continue
            if attempted is not None:
                raise ValueError("PROCESSING_CONDITION_RELEASE_UNCERTAIN")
            fact = self.evidence.find_evidence(activation.effect_id)
            if fact is None or fact.outcome != "completed":
                raise ValueError("PROCESSING_CONDITION_ACTIVATION_UNCERTAIN")
            desc = activation.context["description"]
            targets = tuple(ResolvedContainerRef(t) for t in desc["retained_condition"]["targets"])
            intent = MagneticReleaseIntent(release_id, targets, activation.context["step_id"])
            fields = {key: activation.context[key] for key in PlanContext.__dataclass_fields__}
            fields["resource_ids"] = tuple(fields["resource_ids"])
            context = PlanContext(**fields)
            plan = self.gateway.prepare_processing(release_id, intent, context, ())
            # No-action preparation proves a live condition before any removal.
            if desc["retained_condition"].get("release_kind") == "remove_labware":
                if self.motions is None:
                    raise ValueError("PROCESSING_RELEASE_MOTION_UNAVAILABLE")
                self.motions.finish_condition(activation)
            attempt_id = str(uuid4())
            permit = self.resource.acquire(plan, attempt_id)
            try:
                self.resource.require_consumables(plan)
                self.resource.validate_permit(permit)
                attempt = self.evidence.record_intent(plan, attempt_id)
                self.resource.authorize_dispatch(permit)
                receipt = self.gateway.execute(plan, permit, attempt_id)
                value = self.evidence.ingest(self.evidence.normalize(attempt, receipt))
                if not self.release_completed(activation):
                    raise ValueError("PROCESSING_CONDITION_RELEASE_UNCERTAIN")
                self.resource.settle(attempt_id, value)
            except BaseException:
                if self.evidence.find_attempt(release_id) is None:
                    self.resource.abandon_preparation(permit)
                raise


class ProcessingConditionProjectionInteractor:
    """Project passive condition releases locally; never prepare or execute a device."""
    def __init__(self, processing, space, snapshot, placement):
        self.processing, self.space = processing, space
        self.snapshot, self.placement = snapshot, placement

    def before_effect(self, pending, retained, projected):
        from .preparation import MagneticEnvironmentInteractor
        if retained and not MagneticEnvironmentInteractor().retains(pending):
            return self.release(retained, projected)
        return retained, projected

    def after_effect(self, pending, allocations, retained, projected):
        from ..models import MagneticSeparationIntent, ProjectedConditionRelease
        if pending.prepared.runtime_step.op != 'sep':
            return retained
        intent = self.processing.resolve_intent(pending)
        if not isinstance(intent, MagneticSeparationIntent):
            return retained
        layout = self.space.preview(self.space.scope_for_effect(pending), pending.before_material_state, allocations)
        _, module = self.processing.bind_intent(intent, layout, self.snapshot, projected[1])
        capability = self.snapshot.processing_capabilities[intent.capability][module]
        destination = capability.get('release_destination')
        if destination is None:
            return retained
        if any(condition.module_id == module for condition in retained):
            raise ValueError('PROCESSING_CONDITION_ALREADY_RETAINED')
        labware = next(b.labware for b in layout.bindings if b.reference in intent.targets)
        return (*retained, ProjectedConditionRelease(module, labware, f'module:{module}', destination))

    def release(self, retained, projected):
        for condition in retained:
            projected = self.placement.project_move(condition.labware, condition.source,
                                                    condition.destination, projected)
        return (), projected
