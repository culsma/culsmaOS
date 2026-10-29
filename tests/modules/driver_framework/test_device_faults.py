"""Actual plugin translators and OS models/persistence; no mocked behavior."""
from dataclasses import replace
import sqlite3
import pytest
from culsma_os.driver_framework.models import PlanContext, PreparedDevicePlan, ExecutionBatchIntent
from culsma_os.driver_framework.interactors import NormalizedReceiptInteractor, DeviceFaultInteractor
from culsma_os.program_manager.models import RunRecord
from culsma_os.program_manager.repositories.runs import SqliteTaskRepository
from culsma_os.program_manager.interactors.guidance import RunGuidanceInteractor
HamiltonFaultMappingInteractor = pytest.importorskip('culsma_driver_hamilton.interactors.fault_interactor').HamiltonFaultMappingInteractor
from culsma_driver_hamilton.simulation.models import SimulationError
OpentronsFaultMappingInteractor = pytest.importorskip('culsma_opentrons.faults').OpentronsFaultMappingInteractor
from opentrons.protocol_api.labware import OutOfTipsError


def plan():
    return PreparedDevicePlan('effect',ExecutionBatchIntent('step',()),
        PlanContext('run','device','simulation','r1','layout','simulation',()),None,{})


def payload(details,outcome='unknown'):
    return {'mode':'simulation','step_id':'step','configuration_revision':'r1',
            'outcome':outcome,'payload':details,'consumed_resources':{}}


@pytest.mark.parametrize('mapper,raw,expected',[
    (HamiltonFaultMappingInteractor(),{'backend':{'diagnostic':'HAM_LOCAL_TIP_UNAVAILABLE'}},'TIP_UNAVAILABLE'),
    (HamiltonFaultMappingInteractor(),{'backend':{'diagnostic':'HAM_LOCAL_INVENTORY_INSUFFICIENT'}},'LIQUID_INSUFFICIENT'),
    (HamiltonFaultMappingInteractor(),{'backend':{'diagnostic':'HAM_AGENT_OBSERVATION_UNCERTAIN'}},'COMMUNICATION_LOST'),
    (HamiltonFaultMappingInteractor(),{'backend':{'diagnostic':'HAM_LOCAL_HIG_NOT_STOPPED'}},'DEVICE_NOT_READY'),
    (OpentronsFaultMappingInteractor(),{'exception_type':OutOfTipsError.__name__},'TIP_UNAVAILABLE'),
    (OpentronsFaultMappingInteractor(),{'exception_type':'UnrecognizedNativeError','message':'liquid missing tip'},'DEVICE_ERROR'),
])
def test_driver_maps_fault_into_identity_checked_os_receipt(mapper,raw,expected):
    receipt=NormalizedReceiptInteractor(mapper).map(plan(),payload(raw))
    assert receipt.outcome=='unknown'
    assert receipt.faults[0].code==expected
    assert receipt.faults[0].execution_state=='unknown'
    assert receipt.faults[0].operation_id=='step'
    assert receipt.faults[0].location is None
    assert receipt.payload['faults'][0]['native_details']


def test_mismatched_identity_does_not_offer_a_precise_fault():
    raw=payload({'backend':{'diagnostic':'HAM_LOCAL_TIP_UNAVAILABLE'}})
    raw['step_id']='another'
    receipt=NormalizedReceiptInteractor(HamiltonFaultMappingInteractor()).map(plan(),raw)
    assert receipt.outcome=='unknown' and not receipt.faults


@pytest.mark.parametrize('change',[{'code':'VENDOR_123'},{'execution_state':'retry_safe'},{'source':'sensor_assumed'}, {'location':42}])
def test_invalid_fault_cannot_claim_success(change):
    fault=HamiltonFaultMappingInteractor().preparation(SimulationError('HAM_LOCAL_TIP_UNAVAILABLE'),'step')[0]
    receipt=NormalizedReceiptInteractor().map(plan(),payload({'faults':[{**fault,**change}]},'completed'))
    assert receipt.outcome=='unknown' and not receipt.faults
    assert receipt.payload['fault_contract_error']=='DEVICE_FAULT_INVALID'


def test_preparation_fault_survives_reopening_legacy_run_database(tmp_path):
    path=tmp_path/'runs.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE os_runs(run_id TEXT PRIMARY KEY,status TEXT,checkpoint TEXT,revision INTEGER,error TEXT)')
        repo=SqliteTaskRepository(connection)
        original=repo.save(RunRecord('run','ready','checkpoint'))
        error=NormalizedReceiptInteractor(HamiltonFaultMappingInteractor()).preparation(SimulationError('HAM_LOCAL_INVENTORY_INSUFFICIENT'),'step')
        repo.save(replace(original,status='failed',body_outcome='failed',faults=error.faults))
    with sqlite3.connect(path) as connection:
        record=SqliteTaskRepository(connection).get('run')
        assert record.faults[0]['code']=='LIQUID_INSUFFICIENT'
        guidance=RunGuidanceInteractor().describe({'status':'failed','result':{'os':{'faults':record.faults}},
            'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'recorded','attempts':[]}})
        assert guidance['title']=='The liquid supply needs attention'
        assert 'replace_tips' not in guidance['actions']


def test_execution_fault_explains_problem_without_authorizing_resume():
    receipt=NormalizedReceiptInteractor(HamiltonFaultMappingInteractor()).map(plan(),payload({'backend':{'diagnostic':'HAM_LOCAL_TIP_UNAVAILABLE'}}))
    guidance=RunGuidanceInteractor().describe({'status':'needs_reconciliation','result':{'os':{'unresolved_material_effects':['effect']}},
        'execution_evidence':{'schema':'culsma_run_evidence_v1','accounting':'recorded',
        'attempts':[{'evidence':{'payload':receipt.payload}}]}})
    assert guidance['title']=='Tips need attention'
    assert guidance['actions']==['open_workstation','refresh']
    assert 'isolated' in ' '.join(guidance['next_steps'])
