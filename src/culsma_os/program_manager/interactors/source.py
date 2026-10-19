"""Program-owned source inspection shared by console use cases."""
import re
from culsma.parser.parser import parse_file
from culsma.pipeline.plan_nodes import PlanStepTree
from ..models import ConsoleProgramError, ProgramSourceRepository


class ProgramSourceInteractor:
    validation_scope = 'Language compilation and hosted-operation checks only; the resident worker checks device configuration, workspace and resources before execution.'

    def __init__(self, sources: ProgramSourceRepository, compilation, semantics):
        self.sources, self.compilation, self.semantics = sources, compilation, semantics

    def list(self):
        return self.sources.list()

    def snapshot(self, snapshot_id=None):
        if not self.sources.enabled():
            raise ConsoleProgramError('PROGRAM_LIBRARY_DISABLED','unavailable')
        return self.sources.capture() if snapshot_id is None else self.sources.load(snapshot_id)

    def review(self, program_id, snapshot_id):
        snapshot = self.snapshot(snapshot_id)
        return self.inspect_snapshot(snapshot,program_id)

    def validate_imports(self, snapshot, program_id):
        visited = set()
        pending = [program_id]
        while pending:
            name = pending.pop()
            if name in visited: continue
            visited.add(name)
            program = parse_file(snapshot.directory/name)
            for declaration in program.library_imports:
                module = declaration.name
                if (not isinstance(module,str) or re.fullmatch(r'[A-Za-z0-9_./-]+',module) is None
                        or module.startswith('/') or any(part in {'','.','..'} for part in module.split('/'))):
                    raise ConsoleProgramError('PROGRAM_IMPORT_OUTSIDE_LIBRARY')
                target = module+'.culs'
                if target not in snapshot.files:
                    raise ConsoleProgramError('PROGRAM_IMPORT_NOT_FOUND')
                pending.append(target)

    def inspect_snapshot(self, snapshot, program_id):
        if program_id not in snapshot.files:
            raise ConsoleProgramError('PROGRAM_NOT_FOUND','not_found')
        try:
            self.validate_imports(snapshot,program_id)
            compiled = self.compilation.compile([snapshot.directory/program_id],library_roots=(snapshot.directory,))
        except ConsoleProgramError:
            raise
        except Exception as error:
            code = str(error).split(':',1)[0]
            if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) is None:
                code = 'PROGRAM_COMPILE_FAILED'
            return {'program_id':program_id,'snapshot_id':snapshot.snapshot_id,'valid':False,
                    'scope':self.validation_scope,'diagnostics':[{'code':code,'severity':'error'}],
                    'allocations':[],'operations':[]}
        diagnostics = [*compiled.semantic.diagnostics,*compiled.typed.diagnostics,*compiled.plan.diagnostics,
                       *self.semantics.validate_plan(compiled.plan)]
        steps = [step for protocol in compiled.plan.plans for step in PlanStepTree.leaves(protocol.steps)]
        return {'program_id':program_id,'snapshot_id':snapshot.snapshot_id,
                'valid':not any(d.severity=='error' for d in diagnostics),'scope':self.validation_scope,
                'configuration':'running_service','diagnostics':[d.to_dict() for d in diagnostics],
                'allocations':[{'allocation_id':step.step_id,'name':step.args.get('container_name',step.args.get('bind'))} for step in steps if step.op=='AllocContainer'],
                'operations':sorted(set(step.op for step in steps)),
                'source':self.sources.read_source(snapshot,program_id)}

