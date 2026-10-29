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
    ('preview_program',{'program_id':'transfer.culs'},'programs','preview'),
    ('inspect_program',{'program_id':'transfer.culs'},'programs','inspect'),
    ('start_program',{'program_id':'transfer.culs','snapshot_id':'snapshot','request_id':'start'},'programs','start'),
    ('submit_program',{'program_id':'transfer.culs','snapshot_id':'snapshot','request_id':'submit'},'programs','submit'),
    ('control_request_status',{'run_id':'run','request_id':'pause'},'programs','control-status'),
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


@pytest.mark.parametrize('method,arguments,action',[
    ('view_state',{},'sessions'),
    ('view_request_status',{'request_id':'show'},'receipt'),
    ('open_view',{'session_id':'s','epoch':'e','expected_revision':0,'request_id':'show','view':'experiment','entity_id':'run'},'open'),
    ('reveal_entity',{'session_id':'s','epoch':'e','expected_revision':0,'request_id':'reveal','entity_id':'plate'},'reveal'),
])
def test_view_tools_delegate_to_shared_use_cases(method,arguments,action):
    read=RecordingUseCase();write=RecordingUseCase()
    adapter=MCPServerAdapter(RecordingUseCase(),RecordingUseCase(),RecordingUseCase(),read,write)
    adapter.raw_credential='Bearer test-automation'
    assert getattr(adapter,method)(**arguments)=={'result':'delegated'}
    raw,request=(read.calls or write.calls)[0]
    assert raw==adapter.raw_credential and request.action==action
    assert len(read.calls)+len(write.calls)==1
    assert not hasattr(adapter,'acknowledge_rendering')


@pytest.mark.parametrize('method,args,action',[
    ('tip_supply',{},'show'),
    ('tip_replacement_status',{'request_id':'box'},'status'),
    ('replace_simulated_tip_box',{'request_id':'box','expected_revision':'a'*64,'resource_id':'tips','positions':['1'],'simulation_acknowledged':True},'replace'),
])
def test_supply_tools_delegate_to_the_shared_authorized_entry(method,args,action):
    supplies=RecordingUseCase()
    adapter=MCPServerAdapter(None,None,None,supplies=supplies)
    adapter.raw_credential='Bearer test-automation'
    assert getattr(adapter,method)(**args)=={'result':'delegated'}
    raw,request=supplies.calls[0]
    assert raw==adapter.raw_credential and request.action==action
    assert len(supplies.calls)==1 and 'origin' not in asdict(request)


@pytest.mark.parametrize('method,arguments,action',[
    ('file_roots',{},'roots'),
    ('list_directory',{'root':'installation','path':'examples','offset':200},'list'),
    ('preview_file',{'root':'programs','path':'notes.txt'},'preview'),
])
def test_filesystem_tools_delegate_with_unchanged_credential(method,arguments,action):
    owner=RecordingUseCase()
    adapter=MCPServerAdapter(RecordingUseCase(),RecordingUseCase(),RecordingUseCase(),file_reads=owner)
    adapter.raw_credential='Bearer test-files'
    assert getattr(adapter,method)(**arguments)=={'result':'delegated'}
    raw,request=owner.calls[0]
    assert raw==adapter.raw_credential and request.action==action
