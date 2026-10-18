"""Hosted execution over the unchanged public Culsma run/Driver boundary."""

from copy import deepcopy
from culsma.common.diagnostics import Diagnostic
from culsma.runtime.executor import run
from culsma.pipeline.plan_nodes import PlanStepTree
from culsma.runtime.user_result import build_unexecuted_report
from culsma_os.driver_framework.adapters.semantic import SemanticReplayDriver
from ..models import (
    HostedRunResult,
    RecordedEffect,
    HostContractError,
    HostedEffectPending,
    PendingEffectGroup, GroupEffectResolution, RecordedEffectGroup, ProgramPreflightPort,
)
from .codec import RuntimeCheckpointCodecInteractor
from .replay import ReplayEffectInteractor
from .verification import CheckpointVerificationInteractor
from .workspace import WorkspaceCheckpointInteractor


class HostedRuntimeInteractor:
    def __init__(self, codec=None, processing_capabilities=None, preflight: ProgramPreflightPort | None = None):
        self.codec = codec or RuntimeCheckpointCodecInteractor()
        self.preflight = preflight
        self.processing_capabilities = deepcopy(processing_capabilities)
        self.verification = CheckpointVerificationInteractor()

    def validate_plan(self, plan):
        declarations = ReplayEffectInteractor.bootstrap_ops | {
            "FinalizeContainerContents"
        }
        allowed = declarations | {
            "Mutation",
            "env_hold",
            "agit",
            "sep",
            "assign_local",
            "assign_member",
            "append",
            "control_break",
            "control_continue",
        }
        diagnostics = []
        seen_external = False
        for protocol in plan.plans:
            for step in PlanStepTree.leaves(protocol.steps):
                program = step.args.get("program", {})
                unsupported_separation = (step.op == "sep" and (
                    not isinstance(program, dict) or program.get("kind") != "IRCall"
                    or program.get("name") not in {"magnetic_program", "centrifuge_program"}
                    or (program.get("name") == "centrifuge_program"
                        and self.processing_capabilities is not None
                        and not self.processing_capabilities.get("centrifuge"))))
                if step.op not in allowed or unsupported_separation or (
                    seen_external and step.op in declarations
                ):
                    diagnostics.append(
                        Diagnostic(
                            "HOST_OPERATION_UNSUPPORTED",
                            f"Hosted profile supports leading declarations, liquid Transfer, explicit thermal hold, orbital agitation, centrifugation and in-place magnetic/centrifugal separation; unsupported {step.op}",
                            step.span,
                            node_id=step.step_id,
                        )
                    )
                seen_external = seen_external or step.op in {"Mutation", "env_hold", "agit", "sep"}
        return diagnostics

    def create(self, plan, state, scope_id):
        if any(status != 'pending' for status in state.step_status.values()) or state.locks or state.history:
            raise HostContractError('HOST_INITIAL_STATE_NOT_FRESH: continue through the saved checkpoint')
        initial = deepcopy(state)
        data = {
            "schema": 3 if any(step.op == "MutationGroup" for p in plan.plans for step in p.steps) else 2,
            "scope_id": scope_id,
            "carrier_contract": 1,
            "plan": deepcopy(plan),
            "plan_fingerprint": self.codec.fingerprint(plan),
            "initial_state": initial,
            "initial_fingerprint": self.codec.fingerprint(initial),
            "state": deepcopy(initial),
            "diagnostics": list(plan.diagnostics) + self.validate_plan(plan),
            "pending": None,
            "confirmed": [],
            "finished": False,
            "result": None,
        }
        return self.codec.dumps(data)

    def restore(self, checkpoint):
        data = self.codec.loads(checkpoint)
        if type(data.get("schema")) is not int or data.get("schema") not in {2, 3, 4}:
            raise HostContractError(
                "HOST_CHECKPOINT_SCHEMA_UNSUPPORTED: requires version 2, 3 or 4; historical records remain isolated"
            )
        if self.codec.fingerprint(data["plan"]) != data["plan_fingerprint"]:
            raise HostContractError("HOST_CHECKPOINT_PLAN_MISMATCH")
        if self.codec.fingerprint(data["initial_state"]) != data["initial_fingerprint"]:
            raise HostContractError("HOST_CHECKPOINT_INITIAL_MISMATCH")
        contract = data.get('carrier_contract', 0)
        if type(contract) is not int or contract not in {0, 1}:
            raise HostContractError('HOST_CHECKPOINT_LANGUAGE_CONTRACT_UNSUPPORTED')
        WorkspaceCheckpointInteractor(self.codec).read(data)
        pending = data["pending"]
        waiting = [k for k, v in data["state"].step_status.items() if v == "waiting"]
        if pending is None:
            if waiting:
                raise HostContractError("HOST_CHECKPOINT_PENDING_MISSING")
        else:
            expected_step = pending.step_id if isinstance(pending, PendingEffectGroup) else pending.prepared.runtime_step.step_id
            if (waiting != [expected_step]
                or pending.effect_id != f'{data["scope_id"]}:{expected_step}'
                or data["finished"]
                or (isinstance(pending, PendingEffectGroup) and not WorkspaceCheckpointInteractor.groups_enabled(data))):
                raise HostContractError("HOST_CHECKPOINT_EFFECT_MISMATCH")
            if pending.before_material_state != data["state"].artifacts.get(
                "material_state"
            ):
                raise HostContractError("HOST_CHECKPOINT_MATERIAL_MISMATCH")
        if pending is not None and not self.verification.is_verified(checkpoint):
            self.verify_pending(data)
            self.verification.remember(checkpoint)
        return data, None

    def verify_pending(self, data):
        state = deepcopy(data["initial_state"])
        effects = ReplayEffectInteractor(data, state, self.codec)
        try:
            run(data["plan"], SemanticReplayDriver(effects), state)
        except HostedEffectPending:
            if (
                effects.cursor != len(data["confirmed"])
                or self.codec.fingerprint(effects.pending)
                != self.codec.fingerprint(data["pending"])
                or self.codec.fingerprint(state)
                != self.codec.fingerprint(data["state"])
            ):
                raise HostContractError("HOST_CHECKPOINT_REPLAY_MISMATCH")
            return
        raise HostContractError("HOST_CHECKPOINT_PENDING_UNREACHABLE")

    def recompute(self, data):
        state = deepcopy(data["initial_state"])
        effects = ReplayEffectInteractor(data, state, self.codec)
        if any(d.severity == "error" for d in data["diagnostics"]):
            report = build_unexecuted_report(
                ok=False,
                diagnostics=data["diagnostics"],
                state=state,
                plan=data["plan"],
                initial_material_state=state.artifacts.get("material_state"),
            )
            result = HostedRunResult(
                state, diagnostics=data["diagnostics"], user_result=report, settled=True
            )
        else:
            try:
                result = run(data["plan"], SemanticReplayDriver(effects), state)
            except HostedEffectPending:
                if effects.cursor != len(data["confirmed"]):
                    raise HostContractError("HOST_REPLAY_JOURNAL_INCOMPLETE")
                data.update(
                    state=state, pending=effects.pending, finished=False, result=None
                )
                return self.codec.dumps(data)
            if effects.cursor != len(data["confirmed"]):
                raise HostContractError("HOST_REPLAY_JOURNAL_INCOMPLETE")
        data.update(state=result.state, pending=None, finished=True, result=result)
        return self.codec.dumps(data)

    def validate_admission(self, data):
        # Queued programs can be created by the device-free resident command channel.
        # Recheck the worker's concrete capability snapshot before any external effect.
        if data["confirmed"] or data["pending"] is not None or data["finished"]:
            return
        known = {(d.code, d.message, d.node_id) for d in data["diagnostics"]}
        for diagnostic in self.validate_plan(data["plan"]):
            key = (diagnostic.code, diagnostic.message, diagnostic.node_id)
            if key not in known:
                data["diagnostics"].append(diagnostic)
                known.add(key)

        if self.preflight is not None and not any(d.severity == "error" for d in data["diagnostics"]):
            report, diagnostics = self.preflight.inspect(data["plan"], data["initial_state"], data["scope_id"])
            data["preflight"] = report
            data["diagnostics"].extend(diagnostics)

    def advance(self, checkpoint):
        data, _ = self.restore(checkpoint)
        if data["pending"] is not None or data["finished"]:
            return checkpoint
        self.validate_admission(data)
        return self.recompute(data)

    def pending(self, checkpoint):
        return self.restore(checkpoint)[0]["pending"]

    def resume(self, checkpoint, resolution):
        data, _ = self.restore(checkpoint)
        pending = data["pending"]
        if pending is None or pending.effect_id != resolution.effect_id:
            raise HostContractError("HOST_RESOLUTION_EFFECT_MISMATCH")
        if isinstance(pending, PendingEffectGroup):
            if (not isinstance(resolution, GroupEffectResolution)
                    or tuple(r.effect_id for r in resolution.members) != tuple(m.effect_id for m in pending.members)
                    or any(self.codec.fingerprint(m.prepared.material_result.material_state) != value.proposed_state_fingerprint
                           for m, value in zip(pending.members, resolution.members))):
                raise HostContractError("HOST_GROUP_RESOLUTION_MISMATCH")
            data["confirmed"].append(RecordedEffectGroup(pending.effect_id, self.codec.fingerprint(pending), resolution))
            data["pending"] = None
            return self.recompute(data)
        if (
            self.codec.fingerprint(pending.prepared.material_result.material_state)
            != resolution.proposed_state_fingerprint
        ):
            raise HostContractError("HOST_RESOLUTION_MATERIAL_MISMATCH")
        data["confirmed"].append(
            RecordedEffect(
                pending.effect_id,
                self.codec.fingerprint(pending.prepared),
                self.codec.fingerprint(pending.before_material_state),
                resolution,
            )
        )
        data["pending"] = None
        return self.recompute(data)

    def result(self, checkpoint):
        data, _ = self.restore(checkpoint)
        if data["finished"]:
            result = data["result"]
            return HostedRunResult(
                result.state,
                result.events,
                result.diagnostics,
                result.user_result,
                result.material_accounting,
                settled=True,
            )
        report = build_unexecuted_report(
            ok=False,
            diagnostics=data["diagnostics"],
            state=data["state"],
            plan=data["plan"],
            initial_material_state=data["initial_state"].artifacts.get(
                "material_state"
            ),
        )
        return HostedRunResult(
            data["state"],
            diagnostics=data["diagnostics"],
            user_result=report,
            settled=False,
        )
