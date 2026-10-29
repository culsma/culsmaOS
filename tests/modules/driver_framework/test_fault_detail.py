"""Versioned fault contract with real DTOs; no native fixtures in OS tests."""
from copy import deepcopy
import pytest
from culsma_os.driver_framework.interactors import DeviceFaultInteractor


def fault(**changes):
    return dict(code='DEVICE_ERROR',source='driver',execution_state='unknown',operation_id='step',
                location=None,native_details={},schema='culsma_device_fault_v2',
                reason='culsma.tip.pickup_failed',basis='device_feedback',
                context={'channel':'1','planned_location':'B / 4'},stop_observation={'state':'unknown'},**changes)


def test_v1_round_trip_has_no_new_fields():
    value={k:v for k,v in fault().items() if k not in {'schema','reason','basis','context','stop_observation'}}
    assert DeviceFaultInteractor().validate([value]) == (value,)


def test_unknown_reason_is_valid_and_multiple_faults_are_retained():
    first=fault(); second=deepcopy(first);second['reason']='future.module.new_reason'
    second['context']['channel']='2'
    assert len(DeviceFaultInteractor().validate([first,second])) == 2


@pytest.mark.parametrize('key,value',[
    ('schema','v99'),('reason','bad reason'),('basis','guessed'),
    ('context',{'requested':float('nan'),'unit':'uL'}),
    ('context',{'requested':12}),('context',{'channel':False}),
    ('context',{'vendor_code':'ABC'}),
    ('stop_observation',{'state':'confirmed_stopped'}),
])
def test_invalid_details_are_rejected(key,value):
    data=fault();data[key]=value
    with pytest.raises(ValueError,match='DEVICE_FAULT_INVALID'):
        DeviceFaultInteractor().validate([data])


def test_model_state_cannot_claim_reported_location_or_physical_stop():
    data=fault();data['basis']='model_state';data['context']={'reported_location':'A1'}
    with pytest.raises(ValueError):DeviceFaultInteractor().validate([data])
    data['context']={};data['stop_observation']={'state':'confirmed_stopped','scope':'module','evidence_ref':'receipt:1'}
    with pytest.raises(ValueError):DeviceFaultInteractor().validate([data])


def test_confirmed_stop_requires_scoped_device_evidence():
    data=fault();data['stop_observation']={'state':'confirmed_stopped','scope':'module','evidence_ref':'receipt:1'}
    assert DeviceFaultInteractor().validate([data])[0]['stop_observation']['scope']=='module'
