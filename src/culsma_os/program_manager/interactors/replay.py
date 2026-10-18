"""Recompute language state from confirmed effects; this class never calls a device."""

from copy import deepcopy
from dataclasses import replace
from culsma.runtime.values import UNRESOLVED
from culsma.driver.base import DriverCapabilityResult, DriverResult
from culsma.runtime.material.compute import MaterialCompute
from culsma.runtime.values import RuntimeValueResolver
from culsma.pipeline.plan_nodes import PlanStepTree
from .workspace import WorkspaceCheckpointInteractor
from culsma.driver.groups import GroupDriverResult
from ..models import (
    PreparedRuntimeStep,
    PendingEffect,
    HostedEffectPending,
    HostContractError,
    PendingEffectGroup, RecordedEffectGroup, RecordedEffect,
)


class ReplayEffectInteractor:
    bootstrap_ops = frozenset(
        {"AllocContainer", "DefineContent", "LoadContent", "AnnotateContent"}
    )

    def __init__(self, data, state, codec):
        self.supports_group_execution = WorkspaceCheckpointInteractor.groups_enabled(data)
        self.data = data
        self.state = state
        self.codec = codec
        self.cursor = 0
        self.pending = None
        self.steps = {s.step_id: s for p in data["plan"].plans for s in PlanStepTree.leaves(p.steps)}
        self.values = RuntimeValueResolver()
        self.material = MaterialCompute()

    def check(self, step):
        allowed = step.op in self.bootstrap_ops or step.op in {"Mutation", "env_hold", "agit", "sep"}
        return DriverCapabilityResult(
            allowed, "HOST_SUPPORTED" if allowed else "HOST_OPERATION_UNSUPPORTED"
        )

    def execute(self, step):
        if step.op in self.bootstrap_ops:
            return DriverResult(True, "HOST_LANGUAGE_DECLARATION", {"internal": True})
        if step.op not in {"Mutation", "env_hold", "agit", "sep"}:
            raise HostContractError("HOST_OPERATION_UNSUPPORTED")
        pending = self.prepare_effect(step)
        prepared, before, effect_id = pending.prepared, pending.before_material_state, pending.effect_id
        if self.cursor < len(self.data["confirmed"]):
            record = self.data["confirmed"][self.cursor]
            if (
                not isinstance(record, RecordedEffect)
                or record.effect_id != effect_id
                or record.prepared_fingerprint != self.codec.fingerprint(prepared)
                or record.before_fingerprint != self.codec.fingerprint(before)
                or record.resolution.proposed_state_fingerprint
                != self.codec.fingerprint(prepared.material_result.material_state)
            ):
                raise HostContractError("HOST_REPLAY_EFFECT_MISMATCH")
            self.cursor += 1
            return DriverResult(True, record.resolution.code, deepcopy(record.resolution.payload))
        self.pending = pending
        self.state.step_status[step.step_id] = "waiting"
        raise HostedEffectPending()

    def prepare_effect(self, step):
        runtime_step = self.values.resolve_step_args(
            self.steps[step.step_id], self.state
        )
        if step.op == "env_hold":
            runtime_step = self.resolve_environment(runtime_step)
        before = deepcopy(
            self.state.artifacts.get("material_state", {"containers": {}})
        )
        proposal = self.material.apply_step(runtime_step, before)
        if not proposal.ok:
            raise HostContractError("HOST_MATERIAL_PROPOSAL_INVALID")
        prepared = PreparedRuntimeStep(runtime_step, deepcopy(step), proposal)
        effect_id = f'{self.data["scope_id"]}:{step.step_id}'
        return PendingEffect(effect_id, prepared, before)

    def resolve_environment(self, step):
        gate = deepcopy(step.gate or {})
        for environment in [gate.get("env", {}), *(layer.get("env", {}) for layer in gate.get("env_layers", []))]:
            for key, expression in environment.items():
                value = self.values.eval_expr(expression, self.state)
                if value is UNRESOLVED:
                    raise HostContractError("HOST_ENVIRONMENT_UNRESOLVED")
                environment[key] = self.values.value_to_serialized(value)
        return replace(step, gate=gate)

    def prepare_group_effect(self, request):
        members = tuple(PendingEffect(
            f'{self.data["scope_id"]}:{member.runtime_step.step_id}',
            PreparedRuntimeStep(member.runtime_step, member.driver_step, member.material_result),
            deepcopy(member.before_material_state),
        ) for member in request.members)
        if not members:
            raise HostContractError("HOST_GROUP_EMPTY")
        return PendingEffectGroup(f'{self.data["scope_id"]}:{request.step_id}', request.step_id, members, request.source_member_ids)

    def execute_group(self, request):
        pending = self.prepare_group_effect(request)
        members = pending.members
        if self.cursor < len(self.data["confirmed"]):
            record = self.data["confirmed"][self.cursor]
            if (not isinstance(record, RecordedEffectGroup) or record.effect_id != pending.effect_id
                    or record.prepared_fingerprint != self.codec.fingerprint(pending)
                    or tuple(r.effect_id for r in record.resolution.members) != tuple(m.effect_id for m in members)
                    or any(self.codec.fingerprint(m.prepared.material_result.material_state) != value.proposed_state_fingerprint
                           for m, value in zip(members, record.resolution.members))):
                raise HostContractError("HOST_GROUP_REPLAY_MISMATCH")
            self.cursor += 1
            return GroupDriverResult(
                tuple(m.prepared.runtime_step.step_id for m in members),
                tuple(DriverResult(True, value.code, deepcopy(value.payload)) for value in record.resolution.members),
            )
        self.pending = pending
        self.state.step_status[request.step_id] = "waiting"
        raise HostedEffectPending()
