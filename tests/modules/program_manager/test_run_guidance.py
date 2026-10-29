import pytest
from culsma_os.program_manager.interactors.guidance import RunGuidanceInteractor
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.models import ConsoleReadRequest
from tests.support.console.http import ResidentReadFixture


def run(attempts=None,error=None,status='failed'):
    return {'run_id':'run','status':status,'error':error or 'BATCH_PREPARATION_REJECTED: No available tip positions are declared for this run. Replenish or configure tips before starting.',
            'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'recorded','attempts':attempts if attempts is not None else []},'result':{}}


def test_empty_tips_has_actionable_guidance_without_rewriting_failed_record():
    record=run();view=RunGuidanceInteractor().describe(record)
    assert view['title']=='More tips are needed' and view['device_activity']=='none_recorded'
    assert view['actions']==['replace_tips','refresh','open_files']
    assert record['status']=='failed' and 'BATCH_' not in view['message']


@pytest.mark.parametrize('change',[
    {'execution_evidence':None},
    {'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'unavailable','attempts':[]}},
    {'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'recorded','attempts':[{'evidence':None}]}},
    {'result':{'os':{'unresolved_material_effects':['unknown-effect']}}},
])
def test_missing_or_uncertain_evidence_never_offers_a_simple_restart(change):
    value=RunGuidanceInteractor().describe({**run(),**change})
    assert 'open_files' not in value['actions'] and 'replace_tips' not in value['actions']
    assert value['device_activity']!='none_recorded' or value['kind']=='attention'


@pytest.mark.parametrize('status,title',[('completed','Experiment complete'),('cancelled','Experiment cancelled'),('paused','Experiment paused'),('awaiting_setup','Prepare the experiment')])
def test_normal_states_use_plain_titles(status,title):
    assert RunGuidanceInteractor().describe(run(status=status))['title']==title


def test_generic_preparation_and_execution_failures_remain_distinct():
    owner=RunGuidanceInteractor()
    assert owner.describe(run(error='BATCH_PREPARATION_REJECTED: layout rejected'))['kind']=='preparation'
    executed=owner.describe(run(attempts=[{'attempt_id':'sent'}]))
    assert executed['kind']=='attention' and 'open_files' not in executed['actions']


def test_console_read_enriches_existing_record_without_dispatch_or_inventory_mutation():
    resident=ResidentReadFixture();record=run()
    resident.responses['status']={k:v for k,v in record.items() if k!='execution_evidence'}
    resident.responses['run-evidence']=record['execution_evidence']
    result=ConsoleCommandInteractor(resident).execute(ConsoleReadRequest('run','run'))
    assert result.data['user_guidance']['kind']=='preparation'
    assert resident.calls==[{'action':'status','run_id':'run'},{'action':'run-evidence','run_id':'run'}]


@pytest.mark.parametrize('prefix',['','PRE_DISPATCH_REJECTED: ','BATCH_PREPARATION_REJECTED: '])
def test_tip_shortage_is_consistent_across_operation_and_batch_feedback(prefix):
    value=RunGuidanceInteractor().describe(run(error=prefix+'No available tip positions are declared for this run.'))
    assert value['kind']=='preparation' and value['title']=='More tips are needed'


def test_unrecognized_preparation_diagnostic_does_not_claim_prior_device_work():
    value=RunGuidanceInteractor().describe(run(error='UNRECOGNIZED_INTERNAL_CODE: private detail'))
    assert value['title']=='The experiment could not start'
    assert value['device_activity']=='none_recorded'
    assert 'already' not in value['message'] and 'UNRECOGNIZED' not in value['message']


@pytest.mark.parametrize('prefix',['','PRE_DISPATCH_REJECTED: ','BATCH_PREPARATION_REJECTED: ','GROUP_PRE_DISPATCH_REJECTED: '])
def test_simulated_liquid_shortage_explains_persistent_consumption(prefix):
    record=run(error=prefix+'HAM_LOCAL_INVENTORY_INSUFFICIENT')
    view=RunGuidanceInteractor().describe(record)
    assert view['title']=='The simulated liquid supply is insufficient'
    assert 'Replacing a tip box does not replenish liquids' in ' '.join(view['next_steps'])
    assert 'replace_tips' not in view['actions']
    assert record['status']=='failed'
    # The same diagnostic after dispatch is not permission to repeat an action.
    record['execution_evidence']['attempts']=[{'attempt_id':'sent'}]
    assert 'open_files' not in RunGuidanceInteractor().describe(record)['actions']
