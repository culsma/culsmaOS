from .models import RecoveryDecision
from culsma_os.scheduler.models import ExecutionRecoveryPort
from culsma_os.program_manager.models import PendingEffectGroup
from culsma_os.event_journal.models import LogicalCompletion


class RecoveryInteractor:

    def __init__(self, tasks, execution, evidence, material, state, resources, projection=None, logical=None, finalization=None, motions=None, execution_batches: ExecutionRecoveryPort | None = None):
        self.tasks = tasks
        self.execution = execution
        self.evidence = evidence
        self.material = material
        self.state = state
        self.resources = resources
        self.projection = projection
        self.logical = logical
        self.finalization = finalization
        self.motions = motions
        self.execution_batches = execution_batches

    def reconcile(self, run_id):
        if self.execution_batches is not None:
            decision = self.execution_batches.reconcile(run_id)
            if decision is not None:
                return decision
        record = self.tasks.get(run_id)
        if self.finalization is not None and (record.body_outcome is not None or record.status == "cancel_requested"):
            result = self.finalization.finalize(run_id)
            return RecoveryDecision(run_id, "finalized" if result.status in {"completed", "failed", "cancelled"} else "wait", result.status)
        reservations = self.resources.reservations
        if reservations is None:
            return self.reconcile_owned(run_id)
        with reservations.run_guard(run_id):
            return self.reconcile_owned(run_id)

    def reconcile_owned(self, run_id):
        if self.motions is not None and not self.motions.reconcile(run_id):
            return RecoveryDecision(run_id, "wait", "MOTION_RECONCILIATION_REQUIRED")
        record = self.tasks.get(run_id)
        pending = self.execution.pending(run_id)
        if pending is None:
            return RecoveryDecision(run_id, "unchanged", "NO_PENDING_EFFECT")
        if isinstance(pending, PendingEffectGroup):
            return self.reconcile_group(run_id, pending)
        attempt = self.evidence.find_attempt(pending.effect_id)
        if attempt is None:
            completion = self.evidence.find_logical_completion(pending.effect_id)
            if completion is not None and self.logical is not None:
                resolution = self.logical.complete(run_id, pending, completion.mode)
                self.state.mark_ready(run_id, resolution)
                return RecoveryDecision(run_id, "continue", "LOGICAL_COMPLETION_REGISTERED")
            return RecoveryDecision(run_id, "queued", "NO_EXECUTION_INTENT")
        evidence = self.evidence.find_evidence(pending.effect_id)
        if evidence is None:
            self.state.mark_reconciliation_required(run_id, "INTENT_WITHOUT_EVIDENCE")
            return RecoveryDecision(run_id, "wait", "INTENT_WITHOUT_EVIDENCE")
        self.material.bind(run_id, pending, evidence.mode)
        result = self.material.reconcile(pending, evidence)
        if result.ready:
            self.state.mark_ready(run_id, result.resolution)
            self.resources.settle(attempt.attempt_id, evidence)
            return RecoveryDecision(run_id, "continue", "REGISTERED_EVIDENCE")
        self.state.mark_reconciliation_required(run_id, result.reason or "UNKNOWN")
        return RecoveryDecision(run_id, "wait", result.reason or "UNKNOWN")

    def reconcile_unfinished_runs(self):
        decisions = []
        reservations = self.resources.reservations
        for record in self.tasks.unfinished():
            if reservations is not None:
                owner = reservations.get(record.run_id)
                if record.body_outcome is not None and (owner is None or owner.status == "released"):
                    decisions.append(self.reconcile(record.run_id))
                    continue
                if owner is None or owner.status != "active" or owner.owner_id != reservations.owner_id:
                    continue
                with reservations.run_guard(record.run_id):
                    decisions.append(self.reconcile(record.run_id))
            else:
                decisions.append(self.reconcile(record.run_id))
        decisions = tuple(decisions)
        for attempt_id in self.resources.active_attempts():
            attempt = self.evidence.find_attempt_by_id(attempt_id)
            if attempt is None:
                continue
            if reservations is not None:
                owner = reservations.get(attempt.run_id)
                if owner is None or owner.status != "active" or owner.owner_id != reservations.owner_id:
                    continue
            evidence = self.evidence.find_evidence(attempt.effect_id)
            registered = (self.motions.registered(attempt, evidence)
                          if self.motions is not None and self.motions.is_move_attempt(attempt)
                          else self.material.registered_group(attempt.context["member_effect_ids"])
                          if "member_effect_ids" in attempt.context else self.material.registered(attempt.effect_id))
            if evidence and registered:
                self.resources.settle(attempt_id, evidence)
        return decisions

    def reconcile_group(self, run_id, pending):
        attempt = self.evidence.find_attempt(pending.effect_id)
        if attempt is None:
            if self.logical is not None and all(self.logical.is_no_action(m) for m in pending.members):
                resolution = self.logical.complete_group(run_id, pending, "simulation")
                self.state.mark_ready(run_id, resolution)
                return RecoveryDecision(run_id, "continue", "LOGICAL_GROUP_REGISTERED")
            return RecoveryDecision(run_id, "queued", "NO_EXECUTION_INTENT")
        if attempt.context.get("description", {}).get("waves"):
            return self.reconcile_wave_group(run_id, pending, attempt)
        if attempt.context.get("description", {}).get("collective"):
            return self.reconcile_collective_group(run_id, pending, attempt)
        evidences = []
        self.material.bind(run_id, pending.members[0], attempt.mode)
        for member in pending.members:
            fact = self.evidence.find_completion(member.effect_id)
            if fact is None and self.logical is not None and self.logical.is_no_action(member):
                self.logical.complete(run_id, member, attempt.mode)
                fact = self.evidence.find_logical_completion(member.effect_id)
            if fact is None:
                self.state.mark_reconciliation_required(run_id, "GROUP_EVIDENCE_INCOMPLETE")
                return RecoveryDecision(run_id, "wait", "GROUP_EVIDENCE_INCOMPLETE")
            result = (self.material.reconcile_logical(member, fact) if isinstance(fact, LogicalCompletion)
                      else self.material.reconcile(member, fact))
            if not result.ready:
                self.state.mark_reconciliation_required(run_id, result.reason or "GROUP_INCOMPLETE")
                return RecoveryDecision(run_id, "wait", result.reason or "GROUP_INCOMPLETE")
            evidences.append(fact)
        result = self.material.reconcile_group(pending, evidences)
        if not result.ready:
            self.state.mark_reconciliation_required(run_id, result.reason or "GROUP_INCOMPLETE")
            return RecoveryDecision(run_id, "wait", result.reason or "GROUP_INCOMPLETE")
        aggregate = self.evidence.complete_group(attempt)
        self.state.mark_ready(run_id, result.resolution)
        self.resources.settle(attempt.attempt_id, aggregate)
        return RecoveryDecision(run_id, "continue", "GROUP_REGISTERED_EVIDENCE")


    def reconcile_collective_group(self, run_id, pending, attempt):
        shared = self.evidence.find_evidence(pending.effect_id)
        if shared is None:
            self.state.mark_reconciliation_required(run_id, "INTENT_WITHOUT_WAVE_EVIDENCE")
            return RecoveryDecision(run_id, "wait", "INTENT_WITHOUT_WAVE_EVIDENCE")
        self.material.bind(run_id, pending.members[0], attempt.mode)
        evidences = self.evidence.project_collective_members(attempt)
        result = self.material.reconcile_collective_group(pending, evidences)
        if not result.ready:
            self.state.mark_reconciliation_required(run_id, result.reason)
            return RecoveryDecision(run_id, "wait", result.reason)
        self.state.mark_ready(run_id, result.resolution)
        self.resources.settle(attempt.attempt_id, shared)
        return RecoveryDecision(run_id, "continue", "COLLECTIVE_REGISTERED_EVIDENCE")


    def reconcile_wave_group(self, run_id, pending, attempt):
        from dataclasses import replace
        description = attempt.context["description"]
        if self.projection is None:
            raise ValueError("OS_GROUP_PROJECTION_NOT_CONFIGURED")
        projections = self.projection.prepare(pending, description["waves"])
        if self.projection.certificate(pending, projections) != description.get("reorder_certificate"):
            self.state.mark_reconciliation_required(run_id, "COLLECTIVE_CERTIFICATE_MISMATCH")
            return RecoveryDecision(run_id, "wait", "COLLECTIVE_CERTIFICATE_MISMATCH")
        projected = {p.effect_id: p for p in projections}
        by_effect = {m.effect_id: m for m in pending.members}
        self.material.bind(run_id, pending.members[0], attempt.mode)
        for spec in description["waves"]:
            members = tuple(by_effect[i] for i in spec["member_effect_ids"])
            wave_attempt = self.evidence.find_attempt(spec["effect_id"])
            shared = self.evidence.find_evidence(spec["effect_id"])
            if wave_attempt is None or shared is None:
                reason = "WAVE_NOT_EXECUTED" if wave_attempt is None else "INTENT_WITHOUT_WAVE_EVIDENCE"
                if wave_attempt is not None:
                    self.material.mark_wave_uncertain(run_id, members, f"intent:{wave_attempt.attempt_id}")
                self.state.mark_reconciliation_required(run_id, reason)
                return RecoveryDecision(run_id, "wait", reason)
            facts = self.evidence.project_collective_members(wave_attempt)
            wave_pending = replace(pending, effect_id=spec["effect_id"], step_id=spec["step_id"], members=members,
                                   source_member_ids=tuple(m.prepared.runtime_step.step_id for m in members))
            result = self.material.reconcile_projected_wave(wave_pending, facts, tuple(projected[m.effect_id] for m in members))
            if not result.ready:
                self.state.mark_reconciliation_required(run_id, result.reason)
                return RecoveryDecision(run_id, "wait", result.reason)
        facts = tuple(self.evidence.find_evidence(m.effect_id) for m in pending.members)
        result = self.material.resolve_registered_group(pending, facts)
        if not result.ready:
            self.state.mark_reconciliation_required(run_id, result.reason)
            return RecoveryDecision(run_id, "wait", result.reason)
        aggregate = self.evidence.complete_group(attempt)
        self.state.mark_ready(run_id, result.resolution)
        self.resources.settle(attempt.attempt_id, aggregate)
        return RecoveryDecision(run_id, "continue", "WAVES_REGISTERED_EVIDENCE")
