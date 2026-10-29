"""Isolated diagnostics: production receipt validation and operator guidance."""
from uuid import uuid4
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.program_manager.models import ConsoleReadError
from culsma_os.driver_framework.models import PlanContext, PreparedDevicePlan, ExecutionBatchIntent
from culsma_os.program_manager.interactors.guidance import RunGuidanceInteractor


class FaultTestInteractor:
    def __init__(self, port, mapper):
        self.port, self.mapper = port, mapper

    def execute(self, scenario):
        if scenario not in {'tip_unavailable','liquid_insufficient','interrupted'}:
            raise ValueError('DEVELOPER_SCENARIO_INVALID')
        if self.port is None:
            return {'supported':False,'message':'The installed driver has no isolated diagnostic test port.'}
        identity='developer-'+uuid4().hex
        context=PlanContext(identity,'developer-test','simulation','developer-test','developer-test','simulation',())
        plan=PreparedDevicePlan(identity,ExecutionBatchIntent('developer-step',()),context,None,{})
        receipt=self.mapper.map(plan,self.port.execute(scenario))
        run={'run_id':identity,'status':'failed' if receipt.outcome=='rejected' else 'needs_reconciliation',
             'result':{'os':{'mode':'simulation','faults':list(receipt.payload.get('faults',[])) if receipt.outcome=='rejected' else []}},
             'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'recorded',
                 'attempts':[] if receipt.outcome=='rejected' else [{'evidence':{'payload':receipt.payload}}]}}
        return {'supported':True,'test_only':True,'scenario':scenario,'test_id':identity,
            'outcome':receipt.outcome,'faults':receipt.payload.get('faults',[]),
            'guidance':RunGuidanceInteractor().describe(run),
            'flow':['Injected into private model state','Driver converted the diagnostic',
                    'OS validated the fault receipt','Operator guidance generated'],
            'recovery_allowed':False,'station_changed':False}


class DeveloperTestInteractor(AuthorizedInteractor):
    required_capability='programs:execute'

    def __init__(self,tokens,resident):
        super().__init__(tokens)
        self.resident=resident

    def perform(self,request):
        if request.scenario not in {'tip_unavailable','liquid_insufficient','interrupted'}:
            raise ConsoleReadError('DEVELOPER_SCENARIO_INVALID','invalid_request')
        try:
            return self.resident.execute({'action':'developer-test','developer_scenario':request.scenario})
        except OSError as error:
            raise ConsoleReadError('DEVELOPER_HOST_UNAVAILABLE','unavailable') from error
        except ValueError as error:
            raise ConsoleReadError(str(error),'conflict') from error
