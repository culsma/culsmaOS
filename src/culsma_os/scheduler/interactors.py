from uuid import uuid4
from dataclasses import dataclass, replace
from culsma_os.program_manager.models import PendingEffectGroup
from culsma_os.driver_framework.models import GroupGatewayPort
from culsma_os.transfer_engine.models import TransferRequest
from .models import OperationRequest, OperationConditionPort, ExecutionMode, RunExecutionPort
from culsma_os.driver_framework.models import OperationPreparationRequest, OperationPreparationPort
from .repository import OperationRepository
from culsma_os.resource_manager.models import ResourceConflict
from culsma_os.event_journal.models import LogicalCompletion
from culsma_os.program_manager.models import GroupEffectResolution


@dataclass(frozen=True)
class ExecutionStrategyInteractor:
    """Own mode selection for one host instance; consumers see one execute entry.

    The batch port is an OS run executor, not a raw device/HSL runner. It must
    preserve reservations, evidence and registration. Vendor method composition
    is deliberately supplied separately; missing batch support never falls back
    to per-operation dispatch. Completion-unit capabilities do not select a mode.
    """

    tasks: object
    runs: object
    operations: object
    mode: ExecutionMode = ExecutionMode.STEPWISE
    batch: RunExecutionPort | None = None

    def __post_init__(self):
        try:
            mode = ExecutionMode(self.mode)
        except (TypeError, ValueError) as error:
            raise ValueError("EXECUTION_MODE_UNSUPPORTED") from error
        object.__setattr__(self, "mode", mode)
        if mode is ExecutionMode.BATCH and self.batch is None:
            raise ValueError("EXECUTION_BATCH_NOT_CONFIGURED")

    def execute(self, run_id):
        record = self.tasks.get(run_id)
        if record.status not in {"ready", "waiting"}:
            return record
        if self.mode is ExecutionMode.BATCH:
            return self.batch.execute(run_id)
        return self.execute_stepwise(run_id)

    @classmethod
    def configured(cls, tasks, runs, operations):
        mode = operations.gateway.preferred_execution_mode
        return cls(tasks, runs, operations, mode, BatchRunExecutionInteractor(tasks, runs, operations))

    def reconcile(self, run_id):
        reconcile = getattr(self.batch, 'reconcile', None)
        return reconcile(run_id) if reconcile is not None else None

    def execute_stepwise(self, run_id):
        record = self.tasks.get(run_id)
        if record.status == "ready":
            record = self.runs.advance_ready(run_id)
        if record.status == "waiting":
            self.operations.dispatch_ready(run_id)
            record = self.tasks.get(run_id)
        return record


class RunSchedulerInteractor:

    def __init__(self, tasks, execution, reservations=None, device=None, evidence=None):
        self.tasks = tasks
        self.execution = execution
        self.reservations = reservations
        self.device, self.evidence = device, evidence
        self.session_runs = set()

    def advance_ready(self, run_id):
        record = self.tasks.get(run_id)
        if record.status != "ready" or self.reservations is None:
            return self.execution.advance(run_id)
        try:
            self.reservations.acquire(run_id)
            with self.reservations.run_guard(run_id):
                if self.device is not None and run_id not in self.session_runs:
                    try:
                        self.device.admit_session(allow_reconfiguration=self.reservations.owned(run_id).generation == 1)
                        self.device.restore_consumables(self.reservations.device.device_id, self.evidence)
                    except ValueError as error:
                        return self.execution.state.mark_failed(run_id, f"SESSION_CONSUMPTION_STALE: {error}")
                    self.session_runs.add(run_id)
                return self.execution.advance(run_id)
        except ResourceConflict as error:
            return self.tasks.note_blocked(run_id, str(error))


class OperationSchedulerInteractor:

    def __init__(
        self,
        repository: OperationRepository,
        execution,
        transfer,
        resource,
        device,
        space,
        gateway,
        evidence,
        material,
        state,
        groups=None,
        logical=None,
        planners: dict[str, OperationPreparationPort] | None = None,
        motions=None,
        conditions: OperationConditionPort | None = None,
    ):
        self.repository = repository
        self.conditions = conditions
        self.motions = motions
        self.execution = execution
        self.transfer = transfer
        self.resource = resource
        self.device = device
        self.space = space
        self.gateway = gateway
        self.evidence = evidence
        self.material = material
        self.state = state
        self.groups = groups
        self.logical = logical
        self.planners = {"Mutation": transfer} if planners is None else dict(planners)

    def enqueue(self, request):
        self.repository.enqueue(request)

    def dispatch_ready(self, run_id):
        if self.execution.status(run_id) != "waiting":
            return
        reservations = self.resource.reservations
        if reservations is None:
            return self.dispatch_owned(run_id)
        try:
            reservations.acquire(run_id)
            with reservations.run_guard(run_id):
                if self.execution.status(run_id) == "waiting":
                    return self.dispatch_owned(run_id)
        except ResourceConflict:
            return

    def dispatch_owned(self, run_id):
        pending = self.execution.pending(run_id)
        if pending is None:
            return
        try:
            if self.conditions is not None and not self.conditions.before_effect(run_id, pending):
                return
        except ResourceConflict:
            return
        except Exception as error:
            self.state.mark_reconciliation_required(run_id, f"CONDITION_TRANSITION_UNCERTAIN: {error}")
            return
        if self.motions is not None and not self.motions.before_effect(run_id, pending):
            return
        if isinstance(pending, PendingEffectGroup):
            if self.groups is None:
                raise ValueError("OS_GROUP_EXECUTOR_NOT_CONFIGURED")
            return self.groups.dispatch(run_id, pending)
        self.enqueue(OperationRequest(run_id, pending.effect_id))
        if self.evidence.find_attempt(pending.effect_id) is not None:
            self.state.mark_reconciliation_required(run_id, "ATTEMPT_ALREADY_EXISTS")
            return
        try:
            operation = pending.prepared.runtime_step.op
            if operation == "Mutation" and self.logical is not None and self.logical.is_no_action(pending):
                return self.dispatch_no_action(run_id, pending)
            planner = self.planners.get(operation)
            if planner is None:
                raise ValueError("OS_OPERATION_PLANNER_UNAVAILABLE")
            plan = planner.prepare(OperationPreparationRequest(run_id, pending, self.execution.allocations(run_id)))
            self.material.bind(run_id, pending, plan.context.mode)
            attempt_id = str(uuid4())
            permit = self.resource.acquire(plan, attempt_id)
        except ResourceConflict:
            return
        except (ValueError, NotImplementedError) as error:
            self.state.mark_failed(run_id, str(error))
            return
        try:
            self.space.validate_snapshot(run_id, plan.context.layout_revision)
            self.device.validate_ready(plan.context)
            self.resource.require_consumables(plan)
            self.resource.validate_permit(permit)
            attempt = self.evidence.record_intent(plan, attempt_id)
            self.repository.set_status(pending.effect_id, "executing")
            self.resource.authorize_dispatch(permit)
            payload = self.gateway.execute(plan, permit, attempt_id)
            evidence = self.evidence.ingest(self.evidence.normalize(attempt, payload))
            result = self.material.reconcile(pending, evidence)
            if result.ready:
                self.state.mark_ready(run_id, result.resolution)
                self.repository.set_status(pending.effect_id, "completed")
            elif evidence.outcome == "rejected":
                self.state.mark_failed(run_id, "DEVICE_REJECTED")
            else:
                self.state.mark_reconciliation_required(
                    run_id, result.reason or "EXECUTION_UNKNOWN"
                )
            self.resource.settle(attempt_id, evidence)
        except Exception as error:
            if self.evidence.find_attempt(pending.effect_id) is None:
                self.resource.abandon_preparation(permit)
                self.state.mark_failed(run_id, f"PRE_DISPATCH_REJECTED: {error}")
            else:
                self.state.mark_reconciliation_required(
                    run_id, f"DISPATCH_UNCERTAIN: {type(error).__name__}: {error}"
                )


    def dispatch_no_action(self, run_id, pending):
        try:
            resolution = self.logical.complete(run_id, pending, self.device.get(self.transfer.device_id).mode)
            self.state.mark_ready(run_id, resolution)
            self.repository.set_status(pending.effect_id, "completed")
        except Exception as error:
            self.state.mark_reconciliation_required(run_id, f"LOGICAL_COMPLETION_PENDING: {error}")


class GroupOperationInteractor:
    """One group request and permit, with durable ordered member facts."""

    def __init__(self, repository, execution, transfer, resource, device, space, gateway: GroupGatewayPort, evidence, material, state, projection=None, logical=None):
        self.repository, self.execution, self.transfer = repository, execution, transfer
        self.resource, self.device, self.space = resource, device, space
        self.gateway, self.evidence, self.material, self.state = gateway, evidence, material, state
        self.projection = projection
        self.logical = logical

    def dispatch(self, run_id, pending):
        reservations = self.resource.reservations
        if reservations is None:
            return self.dispatch_owned(run_id, pending)
        try:
            reservations.acquire(run_id)
            with reservations.run_guard(run_id):
                if self.execution.status(run_id) == "waiting":
                    return self.dispatch_owned(run_id, pending)
        except ResourceConflict:
            return

    def dispatch_owned(self, run_id, pending):
        self.repository.enqueue(OperationRequest(run_id, pending.effect_id))
        if self.evidence.find_attempt(pending.effect_id) is not None:
            self.state.mark_reconciliation_required(run_id, "GROUP_ATTEMPT_ALREADY_EXISTS")
            return
        try:
            physical = tuple(m for m in pending.members if self.logical is None or not self.logical.is_no_action(m))
            if not physical:
                return self.dispatch_no_action(run_id, pending)
            physical_pending = replace(pending, members=physical,
                source_member_ids=tuple(m.prepared.runtime_step.step_id for m in physical))
            plan = self.transfer.prepare_group(TransferRequest(run_id, physical_pending, self.execution.allocations(run_id)))
            if len(physical) != len(pending.members) and (plan.waves or plan.vendor_plan is not None):
                raise ValueError("TRANSFER_MIXED_COLLECTIVE_PROFILE_UNSUPPORTED")
            projections = ()
            if plan.waves:
                if self.projection is None:
                    raise ValueError("OS_GROUP_PROJECTION_NOT_CONFIGURED")
                projections = self.projection.prepare(pending, plan.description["waves"])
                plan = replace(plan, description={**plan.description,
                    "reorder_certificate": self.projection.certificate(pending, projections)})
            self.material.bind(run_id, pending.members[0], plan.context.mode)
            self.resource.require_consumables(plan)
            attempt_id = str(uuid4())
            permit = self.resource.acquire(plan, attempt_id)
        except ResourceConflict:
            return
        except (ValueError, NotImplementedError) as error:
            self.state.mark_failed(run_id, str(error))
            return
        try:
            self.space.validate_snapshot(run_id, plan.context.layout_revision)
            self.device.validate_ready(plan.context)
            self.resource.validate_permit(permit)
            attempt = self.evidence.record_intent(plan, attempt_id)
            self.resource.authorize_dispatch(permit)
            self.repository.set_status(pending.effect_id, "executing")
            if plan.waves:
                return self.dispatch_waves(run_id, pending, plan, permit, attempt, projections)
            if plan.vendor_plan is not None:
                return self.dispatch_collective(run_id, pending, plan, permit, attempt)
            evidences = []
            plans = {p.effect_id: p for p in plan.members}
            for member in pending.members:
                self.resource.validate_active_permit(permit)
                if member.effect_id not in plans:
                    self.logical.complete(run_id, member, plan.context.mode)
                    evidences.append(self.evidence.find_logical_completion(member.effect_id))
                    continue
                member_plan = plans[member.effect_id]
                self.space.validate_snapshot(run_id, plan.context.layout_revision)
                self.device.validate_ready(plan.context)
                member_attempt_id = str(uuid4())
                member_attempt = self.evidence.record_intent(member_plan, member_attempt_id)
                receipt = self.gateway.execute_group_member(plan, member_plan, permit, attempt_id, member_attempt_id)
                evidence = self.evidence.ingest(self.evidence.normalize(member_attempt, receipt))
                evidences.append(evidence)
                result = self.material.reconcile(member, evidence)
                if not result.ready:
                    self.state.mark_reconciliation_required(run_id, result.reason or "GROUP_MEMBER_UNKNOWN")
                    return
            aggregate = self.evidence.complete_group(attempt)
            result = self.material.reconcile_group(pending, tuple(evidences))
            if not result.ready:
                self.state.mark_reconciliation_required(run_id, result.reason)
                return
            self.state.mark_ready(run_id, result.resolution)
            self.repository.set_status(pending.effect_id, "completed")
            self.resource.settle(attempt_id, aggregate)
        except Exception as error:
            if self.evidence.find_attempt(pending.effect_id) is None:
                self.resource.abandon_preparation(permit)
                self.state.mark_failed(run_id, f"GROUP_PRE_DISPATCH_REJECTED: {error}")
            else:
                self.state.mark_reconciliation_required(run_id, f"GROUP_DISPATCH_UNCERTAIN: {type(error).__name__}: {error}")


    def dispatch_collective(self, run_id, pending, plan, permit, attempt):
        # Every covered member has a durable intent before the shared action.
        for member_plan in plan.members:
            self.evidence.record_intent(member_plan, str(uuid4()))
        self.resource.validate_active_permit(permit)
        self.space.validate_snapshot(run_id, plan.context.layout_revision)
        self.device.validate_ready(plan.context)
        receipt = self.gateway.execute_collective_group(plan, permit, attempt.attempt_id)
        shared = self.evidence.ingest(self.evidence.normalize(attempt, receipt))
        evidences = self.evidence.project_collective_members(attempt)
        result = self.material.reconcile_collective_group(pending, evidences)
        if not result.ready:
            self.state.mark_reconciliation_required(run_id, result.reason or "COLLECTIVE_UNKNOWN")
            return
        self.state.mark_ready(run_id, result.resolution)
        self.repository.set_status(pending.effect_id, "completed")
        self.resource.settle(attempt.attempt_id, shared)


    def dispatch_waves(self, run_id, pending, plan, permit, attempt, projections):
        from dataclasses import replace
        by_effect = {m.effect_id: m for m in pending.members}
        projected = {p.effect_id: p for p in projections}
        for wave in plan.waves:
            self.resource.validate_active_permit(permit)
            self.space.validate_snapshot(run_id, plan.context.layout_revision)
            self.device.validate_ready(plan.context)
            wave_attempt = self.evidence.record_intent(wave, str(uuid4()))
            for member in wave.members:
                self.evidence.record_intent(member, str(uuid4()))
            members = tuple(by_effect[m.effect_id] for m in wave.members)
            wave_pending = replace(pending, effect_id=wave.effect_id, step_id=wave.intent.step_id, members=members,
                                   source_member_ids=tuple(m.prepared.runtime_step.step_id for m in members))
            try:
                receipt = self.gateway.execute_group_wave(plan, wave, permit, attempt.attempt_id, wave_attempt.attempt_id)
                self.evidence.ingest(self.evidence.normalize(wave_attempt, receipt))
            except Exception:
                self.material.mark_wave_uncertain(run_id, members, f"intent:{wave_attempt.attempt_id}")
                raise
            facts = self.evidence.project_collective_members(wave_attempt)
            result = self.material.reconcile_projected_wave(wave_pending, facts, tuple(projected[m.effect_id] for m in members))
            if not result.ready:
                self.state.mark_reconciliation_required(run_id, result.reason)
                return
        facts = tuple(self.evidence.find_evidence(m.effect_id) for m in pending.members)
        result = self.material.resolve_registered_group(pending, facts)
        if not result.ready:
            self.state.mark_reconciliation_required(run_id, result.reason)
            return
        aggregate = self.evidence.complete_group(attempt)
        self.state.mark_ready(run_id, result.resolution)
        self.repository.set_status(pending.effect_id, "completed")
        self.resource.settle(attempt.attempt_id, aggregate)


    def dispatch_no_action(self, run_id, pending):
        try:
            resolution = self.logical.complete_group(run_id, pending, self.device.get(self.transfer.device_id).mode)
            self.state.mark_ready(run_id, resolution)
            self.repository.set_status(pending.effect_id, "completed")
        except Exception as error:
            self.state.mark_reconciliation_required(run_id, f"LOGICAL_GROUP_COMPLETION_PENDING: {error}")


class LogicalEffectInteractor:
    """Coordinate deterministic logical completion without creating device evidence."""

    def __init__(self, transfer, evidence, material, codec):
        self.transfer, self.evidence, self.material, self.codec = transfer, evidence, material, codec

    def is_no_action(self, pending):
        return self.transfer.resolve_execution(pending).intent is None

    def complete(self, run_id, pending, mode):
        if not self.is_no_action(pending):
            raise ValueError("LOGICAL_EFFECT_REQUIRES_DEVICE")
        completion = LogicalCompletion(f"{pending.effect_id}:logical", run_id, pending.effect_id, mode,
            self.codec.fingerprint(pending.prepared), self.codec.fingerprint(pending.before_material_state),
            self.codec.fingerprint(pending.prepared.material_result.material_state),
            {"completion_kind": "logical", "device_action": False})
        self.evidence.record_logical_completion(completion)
        return self.material.reconcile_logical(pending, completion).resolution

    def complete_group(self, run_id, pending, mode):
        if not pending.members or not all(self.is_no_action(m) for m in pending.members):
            raise ValueError("LOGICAL_GROUP_REQUIRES_DEVICE")
        return GroupEffectResolution(pending.effect_id, tuple(self.complete(run_id, m, mode) for m in pending.members))


class MotionSchedulerInteractor:
    """Journal auxiliary carrier moves before the language's pending effect."""
    def __init__(self, motion, execution, gateway, resource, evidence, device, state):
        self.motion, self.execution, self.gateway = motion, execution, gateway
        self.resource, self.evidence, self.device, self.state = resource, evidence, device, state

    def before_effect(self, run_id, pending):
        if isinstance(pending, PendingEffectGroup):
            return True
        routes = self.motion.capabilities.get("before_steps", {}).get(pending.prepared.runtime_step.step_id, ())
        for ordinal in range(len(routes)):
            effect_id = f"{pending.effect_id}/motion/{ordinal}"
            attempted = self.evidence.find_attempt(effect_id)
            if attempted is not None:
                if not self.reconcile_attempt(attempted):
                    return False
                continue
            try:
                revision, positions = self.motion.positions()
                intents, _ = self.motion.route_intents(pending, self.execution.allocations(run_id), positions, revision, start=ordinal)
                layout = self.motion.space.bind(run_id, pending.before_material_state, self.execution.allocations(run_id))
            except Exception as error:
                self.state.mark_failed(run_id, f"MOTION_PRE_DISPATCH_REJECTED: {error}")
                return False
            if not self.dispatch_move(run_id, effect_id, intents[0], layout):
                return False
        return True

    def finish_condition(self, activation):
        effect_id = f"{activation.effect_id}/condition-release/motion"
        attempted = self.evidence.find_attempt(effect_id)
        if attempted is not None:
            if not self.reconcile_attempt(attempted):
                raise ValueError("PROCESSING_RELEASE_MOTION_UNCERTAIN")
            return
        intent = self.motion.condition_release_intent(activation)
        layout = self.motion.space.get(activation.run_id)
        if not self.dispatch_move(activation.run_id, effect_id, intent, layout):
            raise ValueError("PROCESSING_RELEASE_MOTION_UNCERTAIN")

    def condition_release_registered(self, activation):
        effect_id = f"{activation.effect_id}/condition-release/motion"
        attempt = self.evidence.find_attempt(effect_id)
        fact = self.evidence.find_evidence(effect_id)
        if attempt is None or fact is None or not self.registered(attempt, fact):
            return False
        intent = attempt.context["description"]["motion_intent"]
        route = activation.context["description"]["retained_condition"]["release_motion"]
        return (attempt.run_id == activation.run_id
                and attempt.context["configuration_revision"] == activation.context["configuration_revision"]
                and all(intent[key] == route[key] for key in ("labware", "source", "destination")))

    def dispatch_move(self, run_id, effect_id, intent, layout):
        from culsma_os.driver_framework.models import PlanContext
        permit = None
        try:
            snapshot = self.device.get(self.motion.snapshot.device_id)
            resources = tuple(sorted({*snapshot.shared_resources,
                f"{snapshot.mode}:{snapshot.device_id}:gripper",
                f"{snapshot.mode}:{snapshot.device_id}:slot:{intent.source}",
                f"{snapshot.mode}:{snapshot.device_id}:slot:{intent.destination}"}))
            context = PlanContext(run_id, snapshot.device_id, snapshot.mode, snapshot.configuration_revision,
                layout.revision, snapshot.calibration_revision, resources)
            plan = self.gateway.prepare_motion(effect_id, intent, context)
            attempt_id = str(uuid4())
            permit = self.resource.acquire(plan, attempt_id)
            self.motion.space.validate_snapshot(run_id, layout.revision)
            self.resource.require_consumables(plan)
            self.resource.validate_permit(permit)
            attempt = self.evidence.record_intent(plan, attempt_id)
            self.motion.record_intent(attempt)
            self.resource.authorize_dispatch(permit)
            receipt = self.gateway.execute(plan, permit, attempt_id)
            fact = self.evidence.ingest(self.evidence.normalize(attempt, receipt))
            if fact.outcome == 'rejected':
                self.motion.reject(attempt, fact)
                self.resource.settle(attempt_id, fact)
                self.state.mark_failed(run_id, 'MOTION_DEVICE_REJECTED')
                return False
            self.motion.register(attempt, fact)
            self.resource.settle(attempt_id, fact)
            return True
        except ResourceConflict as error:
            if self.evidence.find_attempt(effect_id) is not None:
                self.state.mark_reconciliation_required(run_id, f"MOTION_DISPATCH_UNCERTAIN: {error}")
            elif permit is not None:
                self.resource.abandon_preparation(permit)
            return False
        except Exception as error:
            if self.evidence.find_attempt(effect_id) is None:
                if permit is not None:
                    self.resource.abandon_preparation(permit)
                self.state.mark_failed(run_id, f"MOTION_PRE_DISPATCH_REJECTED: {error}")
            else:
                self.state.mark_reconciliation_required(run_id, f"MOTION_DISPATCH_UNCERTAIN: {error}")
            return False

    def reconcile_attempt(self, attempt):
        fact = self.evidence.find_evidence(attempt.effect_id)
        if fact is not None and fact.outcome == "rejected":
            self.motion.reject(attempt, fact)
            self.resource.settle(attempt.attempt_id, fact)
            self.state.mark_failed(attempt.run_id, "MOTION_DEVICE_REJECTED")
            return False
        try:
            self.motion.register(attempt, fact)
        except ValueError as error:
            self.state.mark_reconciliation_required(attempt.run_id, f"MOTION_RECONCILIATION_REQUIRED: {error}")
            return False
        self.resource.settle(attempt.attempt_id, fact)
        return True

    def reconcile(self, run_id):
        attempts = sorted((a for a in self.evidence.attempts_for_run(run_id) if self.motion.is_move_attempt(a)),
            key=lambda a: a.context["description"]["motion_intent"]["position_revision"])
        for attempt in attempts:
            if not self.reconcile_attempt(attempt):
                return False
        if attempts:
            self.state.restore_motion_waiting(run_id)
        return True

    def is_move_attempt(self, attempt):
        return self.motion.is_move_attempt(attempt)

    def repair_completed(self, run_id):
        attempts = sorted((a for a in self.evidence.attempts_for_run(run_id) if self.is_move_attempt(a)),
            key=lambda a: a.context["description"]["motion_intent"]["position_revision"])
        for attempt in attempts:
            fact = self.evidence.find_evidence(attempt.effect_id)
            if fact is None or fact.outcome != "completed":
                continue
            try:
                self.motion.register(attempt, fact)
            except ValueError:
                continue  # Incomplete proof remains blocked by release_proof.
            self.resource.settle(attempt.attempt_id, fact)

    def registered(self, attempt, evidence):
        return self.motion.is_move_attempt(attempt) and self.motion.registered(attempt.effect_id, evidence)


class BatchRunExecutionInteractor:
    """Prepare once, submit once and replay only confirmed shared evidence."""

    def __init__(self, tasks, runs, operations):
        self.tasks, self.runs, self.operations = tasks, runs, operations
        self.execution = operations.execution
        self.evidence, self.material = operations.evidence, operations.material
        self.resource, self.state = operations.resource, operations.state

    def root_attempt(self, run_id):
        attempts = [a for a in self.evidence.attempts_for_run(run_id)
                    if 'execution_batch' in a.context.get('description', {})]
        if len(attempts) > 1:
            raise ValueError('BATCH_INTENT_CONFLICT')
        return attempts[0] if attempts else None

    def execute(self, run_id):
        record = self.tasks.get(run_id)
        if record.status == 'ready':
            record = self.runs.advance_ready(run_id)
        if record.status != 'waiting':
            return record
        reservations = self.resource.reservations
        try:
            if reservations is None:
                return self.execute_owned(run_id)
            with reservations.run_guard(run_id):
                return self.execute_owned(run_id)
        except ResourceConflict:
            return self.tasks.get(run_id)

    def prepare(self, run_id):
        from dataclasses import asdict
        from hashlib import sha256
        from culsma_os.driver_framework.models import ExecutionBatchIntent
        from culsma_os.program_manager.models import PendingEffectGroup
        units, operations = self.execution.project_batch(run_id)
        if not units:
            raise ValueError('BATCH_EMPTY_PROJECTION')
        members = tuple(m for unit in units for m in (unit.members if isinstance(unit, PendingEffectGroup) else (unit,)))
        first = members[0]
        ops = self.operations
        allocations = self.execution.allocations(run_id)
        layout = ops.space.bind(run_id, first.before_material_state, allocations)
        snapshot = ops.device.get(ops.transfer.device_id)
        base = ops.transfer.prepare_context(run_id, layout, snapshot,
            first.before_material_state if any(hasattr(o.intent, 'aliquots') for o in operations) else None)
        resources = set(base.resource_ids)
        for capability in snapshot.processing_capabilities.values():
            resources.update(f'{snapshot.mode}:{snapshot.device_id}:module:{name}' for name in capability)
        descriptions = []
        for op in operations:
            move = hasattr(op.intent, 'destination')
            description = {'operation_kind': 'labware_move' if move else getattr(op.intent, 'capability', 'transfer')}
            if move:
                description['motion_intent'] = asdict(op.intent)
                resources.update((f'{snapshot.mode}:{snapshot.device_id}:gripper',
                    f'{snapshot.mode}:{snapshot.device_id}:slot:{op.intent.source}',
                    f'{snapshot.mode}:{snapshot.device_id}:slot:{op.intent.destination}'))
            descriptions.append({'effect_id': op.effect_id, 'step_id': op.intent.step_id, 'description': description})
        checkpoint = self.tasks.get(run_id).checkpoint
        step_id = 'batch-' + sha256(checkpoint.encode()).hexdigest()[:24]
        context = replace(base, resource_ids=tuple(sorted(resources)))
        manifest = {'schema': 'culsma_execution_batch_v1', **self.execution.describe_batch(units), 'members': descriptions,
                    'initial_checkpoint': sha256(checkpoint.encode()).hexdigest()}
        if not operations:
            return units, None
        intent = ExecutionBatchIntent(step_id, operations)
        plan = ops.gateway.prepare_batch(f'{run_id}:{step_id}', intent, context, layout.bindings)
        return units, replace(plan, description={**plan.description, 'execution_batch': manifest,
            'member_effect_ids': [m.effect_id for m in members]})

    def execute_owned(self, run_id):
        attempt = self.root_attempt(run_id)
        if attempt is not None:
            return self.reconcile_attempt(attempt)
        permit = None
        try:
            units, plan = self.prepare(run_id)
            if plan is None:
                return self.register_units(run_id, units, {})
            attempt_id = str(uuid4())
            self.material.bind(run_id, units[0].members[0] if isinstance(units[0], PendingEffectGroup) else units[0], plan.context.mode)
            self.resource.require_consumables(plan)
            permit = self.resource.acquire(plan, attempt_id)
            self.operations.space.validate_snapshot(run_id, plan.context.layout_revision)
            self.resource.validate_permit(permit)
            attempt = self.evidence.record_intent(plan, attempt_id)
            self.resource.authorize_dispatch(permit)
            receipt = self.operations.gateway.execute(plan, permit, attempt_id)
            self.evidence.ingest(self.evidence.normalize(attempt, receipt))
            return self.reconcile_attempt(attempt)
        except Exception as error:
            if self.root_attempt(run_id) is not None:
                return self.state.mark_reconciliation_required(run_id, f'BATCH_EXECUTION_UNCERTAIN: {type(error).__name__}: {error}')
            if permit is not None:
                self.resource.abandon_preparation(permit)
            return self.state.mark_failed(run_id, f'BATCH_PREPARATION_REJECTED: {error}')

    def reconcile(self, run_id):
        from culsma_os.recovery_manager.models import RecoveryDecision
        attempt = self.root_attempt(run_id)
        if attempt is None:
            return None
        reservations = self.resource.reservations
        if reservations is None:
            record = self.reconcile_attempt(attempt)
        else:
            owner = reservations.get(run_id)
            if owner is None or owner.status == 'released':
                return None
            with reservations.run_guard(run_id):
                record = self.reconcile_attempt(attempt)
        return RecoveryDecision(run_id, 'wait' if record.status == 'needs_reconciliation' else 'continue', record.status)

    def reconcile_attempt(self, attempt):
        fact = self.evidence.find_evidence(attempt.effect_id)
        if fact is None or fact.outcome == 'unknown':
            return self.state.mark_reconciliation_required(attempt.run_id, 'BATCH_EVIDENCE_INCOMPLETE')
        if fact.outcome == 'rejected':
            self.resource.settle(attempt.attempt_id, fact)
            return self.state.mark_failed(attempt.run_id, 'BATCH_DEVICE_REJECTED')
        facts = {}
        try:
            manifest = attempt.context['description']['execution_batch']
            units = self.execution.restore_batch(manifest)
            members = tuple(m for unit in units for m in (unit.members if isinstance(unit, PendingEffectGroup) else (unit,)))
            if (manifest.get('schema') != 'culsma_execution_batch_v1'
                    or [m.effect_id for m in members] != attempt.context['member_effect_ids']):
                raise ValueError('BATCH_REPLAY_MISMATCH')
            self.execution.verify_batch_snapshot(attempt.run_id, manifest, units)
            for descriptor in manifest['members']:
                child, evidence = self.evidence.project_batch_member(attempt, descriptor)
                if descriptor['description']['operation_kind'] == 'labware_move':
                    self.operations.motions.motion.register(child, evidence)
                else:
                    facts[descriptor['effect_id']] = evidence
            record = self.register_units(attempt.run_id, units, facts)
            self.resource.settle(attempt.attempt_id, fact)
            return record
        except Exception as error:
            return self.state.mark_reconciliation_required(attempt.run_id, f'BATCH_REPLAY_MISMATCH: {error}')

    def register_units(self, run_id, units, facts):
        resolutions = []
        for unit in units:
            members = unit.members if isinstance(unit, PendingEffectGroup) else (unit,)
            values = []
            for member in members:
                evidence = facts.get(member.effect_id)
                if evidence is None:
                    if self.operations.logical is None or not self.operations.logical.is_no_action(member):
                        raise ValueError('BATCH_MEMBER_EVIDENCE_MISSING')
                    value = self.operations.logical.complete(run_id, member, 'simulation')
                else:
                    self.material.bind(run_id, member, evidence.mode)
                    result = self.material.reconcile(member, evidence)
                    if not result.ready:
                        raise ValueError('BATCH_MEMBER_REGISTRATION_INCOMPLETE')
                    value = result.resolution
                values.append(value)
            resolutions.append(GroupEffectResolution(unit.effect_id, tuple(values)) if isinstance(unit, PendingEffectGroup) else values[0])
        record = self.state.register_batch(run_id, units, tuple(resolutions))
        return self.execution.advance(run_id) if record.status == 'ready' else record
