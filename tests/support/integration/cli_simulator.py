from tests.support.paths import ROOT
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.driver_framework.interactors import DriverLoaderInteractor
from culsma.frontend.resolver import resolve_files
from culsma.pipeline.compile import compile_ast
from culsma.pipeline.plan import lower_ir_to_plan
from culsma.pipeline.typecheck import typecheck
from culsma.pipeline.validate import validate
from culsma_opentrons.support import validate_plan_support


culsma_opentrons = pytest.importorskip("culsma_opentrons")


SIMULATOR_FIXTURES = ROOT / 'tests/fixtures/driver_framework/opentrons'


def compile_example(name):
    compiled = compile_ast(
        resolve_files([SIMULATOR_FIXTURES / name / "protocol.culs"]).prepared_program
    )
    validated = validate(compiled.ir, analysis=compiled.analysis, enforce_binding=True)
    typed = typecheck(validated.ir, analysis=compiled.analysis)
    assert validated.ok and typed.ok
    return lower_ir_to_plan(typed.ir, analysis=compiled.analysis)
