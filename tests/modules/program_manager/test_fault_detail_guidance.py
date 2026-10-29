"""Catalogue lookup and shared structured guidance over stored records."""
from copy import deepcopy
from culsma_os.program_manager.interactors.guidance import RunGuidanceInteractor
from tests.modules.driver_framework.test_fault_detail import fault


def view(faults):
    return RunGuidanceInteractor().describe({'status':'needs_reconciliation',
        'result':{'os':{'faults':faults}},'execution_evidence':{
            'schema':'culsma_run_evidence_v1','accounting':'recorded','attempts':[]}})


def test_pickup_failure_explains_position_without_assuming_empty_stock():
    value=view([fault()]); detail=value['fault_details'][0]
    assert value['title']=='Tip pickup failed'
    assert detail['facts']['Planned position']=='B / 4'
    assert 'does not establish' in detail['check']
    assert value['actions']==['open_workstation','refresh']
    assert 'unknown' in value['context']['execution']


def test_multiple_channel_faults_and_unknown_reasons_are_visible():
    first=fault();second=deepcopy(first);second['reason']='future.module.new_reason';second['context']['channel']='2'
    value=view([first,second]);details=value['fault_details']
    assert [d['facts']['Channel'] for d in details]==['1','2']
    assert 'no specific remedy' in details[1]['check']
    assert value['faults'][1]['reason']=='future.module.new_reason'


def test_catalogue_is_data_and_covers_each_published_reason():
    owner=RunGuidanceInteractor()
    assert len({entry.reason for entry in owner.catalog.entries})==len(owner.catalog.entries)
    for entry in owner.catalog.entries:
        value=fault();value['reason']=entry.reason
        assert owner.describe_fault(value)['check']==entry.check
