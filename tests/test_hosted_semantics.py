from dataclasses import replace
from pathlib import Path
import pytest
from culsma.frontend.resolver import resolve_files
from culsma.pipeline.compile import compile_ast
from culsma.pipeline.validate import validate
from culsma.pipeline.typecheck import typecheck
from culsma.pipeline.plan import lower_ir_to_plan
from culsma.pipeline.entrypoints import resolve_entry
from culsma.runtime.state import init_state
from culsma.runtime.executor import run
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.replay import (
    ReplayEffectInteractor as SemanticBoundaryDriver,
)
from culsma_os.program_manager.models import EffectResolution, HostContractError
from culsma.driver.base import DriverResult


class StandaloneTestDriver:
    bootstrap_ops = SemanticBoundaryDriver.bootstrap_ops

    def check(self, step):
        from culsma.driver.base import DriverCapabilityResult

        return DriverCapabilityResult(True, "HOST_SUPPORTED")

    def execute(self, step):
        return (
            DriverResult(True, "HOST_LANGUAGE_DECLARATION", {"internal": True})
            if step.op in self.bootstrap_ops
            else DriverResult(True, "TEST_SIMULATED", {"mode": "simulation"})
        )


class TestHostedRuntime:
    def plan(self):
        path = Path(__file__).parent / "fixtures_hosted/transfer.culs"
        compiled = compile_ast(resolve_files([path]).prepared_program)
        validated = validate(
            compiled.ir, analysis=compiled.analysis, enforce_binding=True
        )
        typed = typecheck(validated.ir, analysis=compiled.analysis)
        return lower_ir_to_plan(
            typed.ir,
            analysis=compiled.analysis,
            entry_resolution=resolve_entry(typed.ir),
        )

    def resolution(self, host, pending):
        from culsma_os.program_manager.models import PendingEffectGroup, GroupEffectResolution
        if isinstance(pending, PendingEffectGroup):
            return GroupEffectResolution(pending.effect_id, tuple(self.resolution(host,m) for m in pending.members))
        return EffectResolution(
            pending.effect_id,
            "evidence",
            "registration",
            host.codec.fingerprint(pending.prepared.material_result.material_state),
            "simulation",
            "TEST_SIMULATED",
            {"mode": "simulation"},
        )

    def test_hosted_semantics_match_standalone(self):
        plan = self.plan()
        standalone = run(plan, StandaloneTestDriver(), init_state(plan))
        host = HostedRuntimeInteractor()
        checkpoint = host.create(plan, init_state(plan), "run")
        while True:
            checkpoint = host.advance(checkpoint)
            pending = host.pending(checkpoint)
            if pending is None:
                break
            # Fresh object restores each boundary; no Python live-stack dependency.
            host = HostedRuntimeInteractor()
            checkpoint = host.resume(checkpoint, self.resolution(host, pending))
        result = host.result(checkpoint)
        assert result.ok and standalone.ok
        assert result.state.to_dict() == standalone.state.to_dict()
        assert result.events == standalone.events
        assert result.material_accounting == standalone.material_accounting
        assert result.user_result == standalone.user_result

    def test_checkpoint_restore_and_duplicate_resolution(self):
        host = HostedRuntimeInteractor()
        plan = self.plan()
        checkpoint = host.advance(host.create(plan, init_state(plan), "run"))
        assert not host.result(checkpoint).ok
        pending = host.pending(checkpoint)
        resolution = self.resolution(host, pending)
        restored = HostedRuntimeInteractor()
        resolved = restored.resume(checkpoint, resolution)
        with pytest.raises(HostContractError):
            restored.resume(resolved, resolution)
        with pytest.raises(HostContractError):
            restored.resume(checkpoint, replace(resolution, effect_id="other"))
        with pytest.raises(HostContractError):
            restored.resume(
                checkpoint, replace(resolution, proposed_state_fingerprint="bad")
            )

    def test_resolution_requires_registration(self):
        with pytest.raises(ValueError):
            EffectResolution("effect", "evidence", "", "hash", "simulation", "ok", {})
        with pytest.raises(ValueError):
            EffectResolution(
                "effect", "evidence", "registration", "hash", "physical", "ok", {}
            )

    def test_unsupported_operation_has_no_actions(self):
        plan = self.plan()
        protocol = plan.plans[0]
        first = replace(protocol.steps[0], op="UnsupportedDeviceOperation")
        plan = replace(
            plan, plans=[replace(protocol, steps=[first, *protocol.steps[1:]])]
        )
        host = HostedRuntimeInteractor()
        checkpoint = host.advance(host.create(plan, init_state(plan), "run"))
        assert host.pending(checkpoint) is None
        assert not host.result(checkpoint).ok

    def test_legacy_checkpoint_is_rejected(self):
        host = HostedRuntimeInteractor()
        plan = self.plan()
        data = host.codec.loads(host.create(plan, init_state(plan), "run"))
        data["schema"] = 1
        with pytest.raises(HostContractError, match="SCHEMA_UNSUPPORTED"):
            host.restore(host.codec.dumps(data))

    def test_tampered_pending_request_is_rejected(self):
        host = HostedRuntimeInteractor()
        plan = self.plan()
        checkpoint = host.advance(host.create(plan, init_state(plan), "run"))
        data = host.codec.loads(checkpoint)
        data["pending"].prepared.driver_step.args["target"] = {
            "kind": "IRIdentifier",
            "name": "other",
        }
        with pytest.raises(HostContractError, match="REPLAY_MISMATCH"):
            host.restore(host.codec.dumps(data))

    def test_changed_initial_state_is_rejected(self):
        host = HostedRuntimeInteractor()
        plan = self.plan()
        data = host.codec.loads(host.create(plan, init_state(plan), "run"))
        data["initial_state"].artifacts["unexpected"] = True
        with pytest.raises(HostContractError, match="INITIAL_MISMATCH"):
            host.restore(host.codec.dumps(data))


class TestHostedGroupRuntime(TestHostedRuntime):
    def test_group_checkpoint_roundtrip(self):
        from culsma.frontend.resolver import resolve_program
        from culsma.parser import parse
        from culsma.pipeline.plan_nodes import PlanStepTree
        source = '''let stock=tube(label="Stock",capacity=2000uL,load=[content(kind=formulation,type=buffer,code="BUFFER"):200uL]);
        let assay=plate(label="Assay",format="96well",capacity=200uL);
        assay[A1:A2] << [stock:20uL];'''
        compiled=compile_ast(resolve_program(parse(source)).prepared_program)
        plan=lower_ir_to_plan(compiled.ir)
        group=next(s for p in plan.plans for s in p.steps if s.op=="MutationGroup")
        member_ids=[s.step_id for s in PlanStepTree.children(group)]
        standalone=run(plan,StandaloneTestDriver(),init_state(plan))
        host=HostedRuntimeInteractor()
        checkpoint=host.create(plan,init_state(plan),"group-run")
        seen=[]
        for _ in range(3):
            host=HostedRuntimeInteractor()
            checkpoint=host.advance(checkpoint)
            pending=host.pending(checkpoint)
            if pending is None:
                break
            seen.extend(m.prepared.runtime_step.step_id for m in pending.members)
            checkpoint=host.resume(checkpoint,self.resolution(host,pending))
        result=host.result(checkpoint)
        assert result.ok and seen==member_ids
        assert result.state.to_dict()==standalone.state.to_dict()
        assert result.events==standalone.events
        # Same envelope is retained in the durable plan throughout member recovery.
        saved=host.codec.loads(checkpoint)
        assert any(s.op=="MutationGroup" for p in saved["plan"].plans for s in p.steps)
