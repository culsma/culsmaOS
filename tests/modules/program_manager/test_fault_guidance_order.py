"""Fault DTO facts, not vendor strings, determine instructions and their order."""
from dataclasses import asdict
import pytest
from culsma_os.driver_framework.models import DeviceFault
from culsma_os.program_manager.interactors.guidance import RunGuidanceInteractor


def guidance(code='TIP_UNAVAILABLE',source='device',state='unknown',location=None,operation='step-3'):
    fault=asdict(DeviceFault(code,source,state,operation,location,{}))
    return RunGuidanceInteractor().describe({'status':'needs_reconciliation' if state!='not_started' else 'failed',
        'result':{'os':{'faults':[fault]}},
        'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'recorded','attempts':[]}})


@pytest.mark.parametrize('code',['TIP_UNAVAILABLE','LIQUID_INSUFFICIENT','LIQUID_NOT_DETECTED','DEVICE_NOT_READY','COMMUNICATION_LOST','DEVICE_ERROR'])
def test_unknown_execution_preserves_materials_and_checks_stop_before_remedy(code):
    view=guidance(code)
    assert 'unchanged' in view['next_steps'][0]
    assert 'confirm it is stopped' in view['next_steps'][1]
    assert 'Not confirmed by the driver' in view['context']['device_stop']
    assert 'unknown' in view['context']['execution']
    assert 'isolated' in view['next_steps'][-1]
    assert view['actions']==['open_workstation','refresh']
    assert 'acknowledgement does not authorize replay' in view['context']['recovery']


def test_tip_and_liquid_replacement_are_conditional_on_stop_and_execution_review():
    for code in ('TIP_UNAVAILABLE','LIQUID_INSUFFICIENT'):
        view=guidance(code)
        assert 'only after safe access and prior execution have been confirmed' in view['next_steps'][2]


def test_refresh_is_not_presented_as_hardware_inspection():
    view=guidance()
    assert 'recorded information only' in ' '.join(view['next_steps'])
    assert 'verify an operator correction' in ' '.join(view['next_steps'])


def test_missing_location_is_explicit_and_known_location_is_preserved():
    assert 'Not supplied' in guidance(operation=None)['context']['operation']
    assert 'no position is inferred' in guidance()['context']['location']
    assert guidance(location='Carrier B / 4')['context']['location']=='Carrier B / 4'


def test_simulation_does_not_request_physical_handling():
    view=guidance(source='simulation')
    assert 'No physical instrument' in view['context']['device_stop']
    assert 'no physical handling' in ' '.join(view['next_steps'])
    assert 'declared tip rack' in ' '.join(view['next_steps'])
    assert 'Replace tips manually' not in ' '.join(view['next_steps'])


def test_pre_execution_rejection_is_distinct_from_in_place_recovery():
    view=guidance(state='not_started')
    assert 'rejected before device execution' in view['context']['execution']
    assert 'start a new attempt' in view['context']['recovery']
    assert 'isolated' not in ' '.join(view['next_steps'])
