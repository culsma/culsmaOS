"""Program-owned source inspection shared by console use cases."""
import re
from culsma.parser.parser import parse_file,parse
from culsma.pipeline.plan_nodes import PlanStepTree
from ..models import ConsoleProgramError, ProgramSourceRepository


class ProgramSourceInteractor:
    validation_scope = 'Language compilation and hosted-operation checks only; the resident worker checks device configuration, workspace and resources before execution.'

    def __init__(self, sources: ProgramSourceRepository, compilation, semantics, *, selected_only=False):
        self.sources, self.compilation, self.semantics = sources, compilation, semantics
        self.selected_only=selected_only

    def list(self):
        return self.sources.list()

    def snapshot(self, snapshot_id=None, program_id=None):
        if not self.sources.enabled():
            raise ConsoleProgramError('PROGRAM_LIBRARY_DISABLED','unavailable')
        return (self.capture_program(program_id) if self.selected_only else self.sources.capture()) if snapshot_id is None else self.sources.load(snapshot_id)

    def import_target(self,module):
        if not isinstance(module,str) or re.fullmatch(r'[A-Za-z0-9_./-]+',module) is None or module.startswith('/') or any(part in {'','.','..'} for part in module.split('/')):
            raise ConsoleProgramError('PROGRAM_IMPORT_OUTSIDE_LIBRARY')
        return module+'.culs'

    def capture_program(self,program_id):
        sources={};pending=[program_id]
        while pending:
            name=pending.pop()
            if name in sources:continue
            value=self.sources.read_live_source(name);sources[name]=value
            if len(sources)>256 or sum(len(v.encode()) for v in sources.values())>2000000:raise ConsoleProgramError('PROGRAM_LIBRARY_TOO_LARGE')
            try:program=parse(value)
            except Exception:continue  # Compilation returns the existing diagnostic for invalid syntax.
            for declaration in program.library_imports:pending.append(self.import_target(declaration.name))
        return self.sources.store_snapshot(sources)

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
                target = self.import_target(module)
                if target not in snapshot.files:
                    raise ConsoleProgramError('PROGRAM_IMPORT_NOT_FOUND')
                pending.append(target)

    def inspect_snapshot(self, snapshot, program_id, *, check_host=True):
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
                    'scope':self.validation_scope,'diagnostics':[self.compilation_diagnostic(error,code)],
                    'allocations':[],'operations':[]}
        diagnostics = [*compiled.semantic.diagnostics,*compiled.typed.diagnostics,*compiled.plan.diagnostics,
                       *(self.semantics.validate_plan(compiled.plan) if check_host else ())]
        steps = [step for protocol in compiled.plan.plans for step in PlanStepTree.leaves(protocol.steps)]
        return {'program_id':program_id,'snapshot_id':snapshot.snapshot_id,
                'valid':not any(d.severity=='error' for d in diagnostics),'scope':self.validation_scope,
                'configuration':'running_service','diagnostics':[d.to_dict() for d in diagnostics],
                'allocations':[{'allocation_id':step.step_id,'name':step.args.get('container_name',step.args.get('bind'))} for step in steps if step.op=='AllocContainer'],
                'operations':sorted(set(step.op for step in steps)),
                'execution_steps':[{'step_id':step.step_id,'operation':step.op,
                    'line':getattr(step.span,'line',None)} for step in steps if step.op in {'Mutation','sep','agit','env_hold','img'}],
                'source':self.sources.read_source(snapshot,program_id)}



    def compilation_diagnostic(self,error,code):
        """Expose source positions supplied by the language parser, without reparsing."""
        result={'code':code,'severity':'error','message':'The program could not be checked.'}
        line,column=getattr(error,'line',None),getattr(error,'column',None)
        if type(line) is int and line>0 and type(column) is int and column>0:
            result.update(message=str(error).splitlines()[0][:500],span={'line':line,'col':column})
        return result
