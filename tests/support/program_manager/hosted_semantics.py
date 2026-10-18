from tests.support.paths import ROOT
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


class HostedRuntimeFixture:
    def plan(self):
        path = ROOT / "tests/fixtures/program_manager/transfer.culs"
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
