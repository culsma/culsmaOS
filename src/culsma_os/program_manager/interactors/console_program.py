"""Authorized console commands use the existing resident queue, never a second worker."""
import re
from culsma_os.auth.interactors import AuthorizedInteractor
from ..models import ConsoleProgramRequest, ConsoleProgramError, ResidentCommandPort


class ConsoleProgramInteractor(AuthorizedInteractor):
    required_capability = 'programs:execute'

    def __init__(self, tokens, source, resident: ResidentCommandPort):
        super().__init__(tokens)
        self.source, self.resident = source, resident

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
            return self.source.list()
        if request.request_id is not None:
            self.validate_identity(request.request_id)
        if request.action in {'pause','resume','cancel','control-status'}:
            self.validate_identity(request.run_id)
            return {'acknowledgement':self.command({'action':request.action,'run_id':request.run_id,'request_id':request.request_id}),
                    'effect':'control_status' if request.action=='control-status' else 'queued_control_request'}
        snapshot = self.source.snapshot(None if request.action == 'inspect' else request.snapshot_id)
        inspection = self.source.inspect_snapshot(snapshot,request.program_id)
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
