"""Compile and validate source using the independent language's public pipeline."""
from copy import deepcopy
import json
from pathlib import Path
from culsma.frontend.resolver import resolve_files
from culsma.pipeline.compile import compile_ast
from culsma.pipeline.entrypoints import resolve_entry
from culsma.pipeline.plan import lower_ir_to_plan
from culsma.pipeline.typecheck import typecheck
from culsma.pipeline.validate import validate
from culsma.runtime.state import init_state
from ..models import CompiledProgram


class CompilationInteractor:
    def compile(self, input_paths, material_state_path=None, library_roots=()):
        if len(input_paths) != 1:
            raise ValueError("RUN_SINGLE_ENTRY_SOURCE_REQUIRED")
        frontend = resolve_files(input_paths, library_roots=library_roots or ())
        compiled = compile_ast(frontend.prepared_program)
        initial = self.load_material_state(material_state_path)
        sem = validate(compiled.ir, analysis=compiled.analysis,
                       initial_defined_names=set(initial.get("containers", {})), enforce_binding=True)
        typ = typecheck(sem.ir, analysis=compiled.analysis)
        plan = lower_ir_to_plan(typ.ir, analysis=compiled.analysis, entry_resolution=resolve_entry(typ.ir))
        state = init_state(plan)
        state.artifacts["material_state"] = deepcopy(initial)
        return CompiledProgram(frontend, compiled.ir, sem, typ, plan, state, initial)

    def load_material_state(self, path):
        if path is None:
            return {"containers": {}}
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("containers"), dict):
            return value
        return {"containers": {}}
