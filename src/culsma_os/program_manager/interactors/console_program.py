"""Authorized console commands use the existing resident queue, never a second worker."""
import re
from culsma.parser.parser import parse_file
from culsma.pipeline.plan_nodes import PlanStepTree
from culsma_os.auth.interactors import AuthorizedInteractor
from ..models import ConsoleProgramRequest, ConsoleProgramError, ProgramSourceRepository, ResidentCommandPort


class ConsoleProgramInteractor(AuthorizedInteractor):
    required_capability = 'programs:execute'
    validation_scope = 'Language compilation and hosted-operation checks only; the resident worker checks device configuration, workspace and resources before execution.'

    def __init__(self, tokens, sources: ProgramSourceRepository, compilation, semantics, resident: ResidentCommandPort):
        super().__init__(tokens)
        self.sources, self.compilation, self.semantics, self.resident = sources, compilation, semantics, resident

    def perform(self, request):
        if not isinstance(request,ConsoleProgramRequest) or not isinstance(request.action,str):
            raise ConsoleProgramError('PROGRAM_REQUEST_INVALID')
        values = {'program_id':request.program_id,'snapshot_id':request.snapshot_id,
                  'request_id':request.request_id,'run_id':request.run_id}
        required = {'list':set(),'inspect':{'program_id'},'submit':{'program_id','snapshot_id','request_id'},
                    'control-status':{'run_id','request_id'},'pause':{'run_id','request_id'},'resume':{'run_id','request_id'},'cancel':{'run_id','request_id'}}
        if (request.action not in required or {key for key,value in values.items() if value is not None} != required[request.action]
                or any(value is not None and (not isinstance(value,str) or not value) for value in values.values())):
            raise ConsoleProgramError('PROGRAM_REQUEST_INVALID')
        if request.action == 'list':
            return self.sources.list()
        if request.request_id is not None:
            self.validate_identity(request.request_id)
        if request.action in {'pause','resume','cancel','control-status'}:
            self.validate_identity(request.run_id)
            return {'acknowledgement':self.command({'action':request.action,'run_id':request.run_id,'request_id':request.request_id}),
                    'effect':'control_status' if request.action=='control-status' else 'queued_control_request'}
        if not self.sources.enabled():
            raise ConsoleProgramError('PROGRAM_LIBRARY_DISABLED','unavailable')
        snapshot = self.sources.capture() if request.action == 'inspect' else self.sources.load(request.snapshot_id)
        if request.program_id not in snapshot.files:
            raise ConsoleProgramError('PROGRAM_NOT_FOUND','not_found')
        inspection = self.inspect_snapshot(snapshot, request.program_id)
        if request.action == 'inspect':
            return inspection
        if not inspection['valid']:
            raise ConsoleProgramError('PROGRAM_DIAGNOSTICS_REJECTED',diagnostics=inspection['diagnostics'])
        result = self.command({'action':'submit','source':str(snapshot.directory/request.program_id),
            'library_roots':[str(snapshot.directory)],'request_id':request.request_id})
        return {'run':result,'snapshot_id':snapshot.snapshot_id,'program_id':request.program_id,
                'configuration':'running_service','effect':'admitted_to_resident_queue'}

    def validate_identity(self, value):
        if re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value) is None:
            raise ConsoleProgramError('PROGRAM_IDENTITY_INVALID')

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

    def command(self, payload):
        try:
            result = self.resident.execute(payload)
        except OSError as error:
            raise ConsoleProgramError('PROGRAM_HOST_RESPONSE_UNAVAILABLE','unavailable') from error
        except ValueError as error:
            code = str(error)
            if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) is None:
                code = 'PROGRAM_HOST_REJECTED'
            kind = 'not_found' if code in {'HOST_RUN_NOT_FOUND','HOST_CONTROL_NOT_FOUND'} else 'conflict'
            raise ConsoleProgramError(code,kind,getattr(error,'diagnostics',())) from error
        if not isinstance(result,dict):
            raise ConsoleProgramError('PROGRAM_HOST_RESPONSE_INVALID','bad_response')
        return result
