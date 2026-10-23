"""Transport contract without requiring the optional MCP SDK in the simulator environment."""
from dataclasses import asdict
import pytest
from culsma_os.console.adapters.mcp import MCPServerAdapter


class RecordingUseCase:
    def __init__(self): self.calls=[]
    def execute(self,raw,request):
        self.calls.append((raw,request))
        return {'result':'delegated'}


@pytest.mark.parametrize('method,arguments,owner,action',[
    ('station_status',{},'observation','station'),
    ('list_runs',{},'observation','runs'),
    ('run_status',{'run_id':'run'},'observation','run'),
    ('loading_plan',{'run_id':'run'},'setup','show'),
    ('revise_loading_plan',{'run_id':'run','fingerprint':'a'*64,'request_id':'revise','fixed':{'alloc':{'labware':'plate','well':'A1'}}},'setup','revise'),
    ('begin_loading',{'run_id':'run','fingerprint':'a'*64,'request_id':'begin'},'setup','begin'),
    ('loading_request_status',{'run_id':'run','request_id':'begin'},'setup','status'),
    ('list_programs',{},'programs','list'),
    ('inspect_program',{'program_id':'transfer.culs'},'programs','inspect'),
    ('submit_program',{'program_id':'transfer.culs','snapshot_id':'snapshot','request_id':'submit'},'programs','submit'),
    ('control_run',{'run_id':'run','action':'cancel','request_id':'cancel'},'programs','cancel'),
])
def test_tools_forward_unchanged_process_credential_and_typed_request(method,arguments,owner,action):
    entries={name:RecordingUseCase() for name in ['setup','programs','observation']}
    adapter=MCPServerAdapter(**entries)
    adapter.raw_credential='Bearer explicit-test-credential'
    assert getattr(adapter,method)(**arguments)=={'result':'delegated'}
    raw,request=entries[owner].calls[0]
    assert raw==adapter.raw_credential and getattr(request,'resource',getattr(request,'action',None))==action
    assert not any(key in asdict(request) for key in ['caller','origin','capabilities','token'])
    assert sum(len(entry.calls) for entry in entries.values())==1
    if method=='revise_loading_plan':
        assert request.preferences=={'fixed':arguments['fixed'],'preferred':{}}
        assert request.fingerprint==arguments['fingerprint']
    if method=='submit_program':
        assert (request.program_id,request.snapshot_id,request.request_id)==('transfer.culs','snapshot','submit')
