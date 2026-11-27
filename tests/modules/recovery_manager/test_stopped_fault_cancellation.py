from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from culsma_os.recovery_manager.cancellation import RunCancellationInteractor
from culsma_os.program_manager.interactors.guidance import RunGuidanceInteractor


def fault():
    return {'schema':'culsma_device_fault_v2','code':'LIQUID_NOT_DETECTED','source':'driver',
        'reason':'culsma.liquid.not_detected','basis':'device_feedback','execution_state':'partial',
        'operation_id':'transfer','location':None,'native_details':{'main_error':102},
        'context':{'channel':'1','planned_location':'F4 / 1'},
        'stop_observation':{'state':'confirmed_stopped','scope':'Hamilton VENUS method','evidence_ref':'a'*64}}


def owner(value=None, **changes):
    receipt=SimpleNamespace(outcome='unknown',mode='physical',attempt_id='a',run_id='r',payload={'faults':[value or fault()]})
    for key,value in changes.items(): setattr(receipt,key,value)
    evidence=Mock()
    evidence.attempts_for_run.return_value=[SimpleNamespace(attempt_id='a',effect_id='e')]
    evidence.find_evidence.return_value=receipt
    return RunCancellationInteractor(evidence,Mock())


def test_stop_requires_matching_original_failed_physical_receipt():
    assert owner().stopped_fault_requires_cancellation('r')
    for change in ({'outcome':'completed'},{'mode':'simulation'},{'attempt_id':'other'},{'run_id':'other'}):
        assert not owner(**change).stopped_fault_requires_cancellation('r')
    value=fault();value['stop_observation']={'state':'unknown'}
    assert not owner(value).stopped_fault_requires_cancellation('r')
    assert not owner({'code':'broken'}).stopped_fault_requires_cancellation('r')


def test_cancelled_fault_guides_new_loading_without_replaying_old_run():
    guidance=RunGuidanceInteractor().describe({'status':'cancelled','result':{'os':{'faults':[fault()]}},
        'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'recorded','attempts':[]}})
    assert 'open_files' in guidance['actions']
    assert 'previous run is closed' in guidance['context']['recovery']
    assert any('next unused tip' in step for step in guidance['next_steps'])
    assert guidance['fault_details'][0]['facts']['Planned position']=='F4 / 1'


@pytest.mark.parametrize('status,expected',[('passed','passed'),('not_monitored','unverified'),('simulated','unverified'),('liquid_level_checked','unverified')])
def test_completion_text_separates_monitoring_and_measured_volume(status,expected):
    attempts=[{'evidence':{'payload':{'liquid_verification':{'aspiration':expected,'volume_measured':False}}}}]
    owner=RunGuidanceInteractor()
    assert owner.pipetting_verification(attempts)==expected
    guidance=owner.describe({'status':'completed','execution_evidence':{
        'schema':'culsma_run_evidence_v1','accounting':'recorded','attempts':attempts}})
    assert guidance['liquid_verification']==expected
    assert ('volume was not measured' in guidance['message']) if expected=='passed' else ('not verified' in guidance['message'])
    assert owner.pipetting_verification([]) is None
