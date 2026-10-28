from dataclasses import replace
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.console_interaction.interactors import (ViewStateReadInteractor, ViewRequestInteractor,
    RendererSessionInteractor, validate_view_state)
from culsma_os.console_interaction.models import (ViewInteractionError, ViewStateReadRequest,
    ViewRequest, RendererSessionRequest)
from culsma_os.console_interaction.repository import SqliteViewInteractionRepository

STATE = {'view':'workstation','entity_id':None,'selected_entity_id':None,'dirty':False,'busy':False}


class Clock:
    def __init__(self): self.now=1000.0
    def __call__(self): return self.now


class Observation:
    def __init__(self): self.calls=[]
    def execute(self, request):
        self.calls.append(request)
        if request.resource=='run':
            return SimpleNamespace(data={'run_id':request.run_id,'status':'completed'})
        return SimpleNamespace(data={'layout':{'status':'available','layout':{
            'definition':{'objects':[{'id':'plate'}]},'configuration':{}}}})


@pytest.fixture
def system(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository())
    repository=SqliteViewInteractionRepository(tmp_path/'views.sqlite3','station')
    clock=Clock();observation=Observation()
    renderer=RendererSessionInteractor(tokens,repository,clock)
    reads=ViewStateReadInteractor(tokens,repository,clock)
    requests=ViewRequestInteractor(tokens,repository,observation,clock)
    return SimpleNamespace(tokens=tokens,repository=repository,clock=clock,observation=observation,
        renderer=renderer,reads=reads,requests=requests,automation='Bearer '+tokens.issue_automation_session(),
        human='Bearer '+tokens.issue_console_session(),renderer_raw='Bearer '+tokens.issue_renderer_session())


def register(s):
    return s.renderer.execute(s.renderer_raw,RendererSessionRequest('register',state=STATE))['session']


def request(session, request_id='show', **changes):
    return replace(ViewRequest('open',request_id,session['session_id'],session['epoch'],session['revision'],'experiment','run-1'),**changes)


def renderer_request(session, action, **changes):
    return RendererSessionRequest(action,session['session_id'],session['epoch'],session['revision'],**changes)


def test_no_ui_has_no_session_and_open_does_not_start_or_observe_run(system):
    s=system
    assert s.reads.execute(s.automation,ViewStateReadRequest())=={'sessions':[]}
    with pytest.raises(ViewInteractionError,match='RENDERER_UNAVAILABLE'):
        s.requests.execute(s.automation,request({'session_id':'missing','epoch':'old','revision':0}))
    assert not s.observation.calls


def test_read_present_and_renderer_authority_are_separate(system):
    s=system;session=register(s)
    for raw in [s.automation,s.human]:
        with pytest.raises(ConsoleAccessError): s.renderer.execute(raw,renderer_request(session,'inspect'))
    for usecase,req in [(s.reads,ViewStateReadRequest()),(s.requests,request(session))]:
        with pytest.raises(ConsoleAccessError): usecase.execute(s.renderer_raw,req)
    other='Bearer '+s.tokens.issue_renderer_session()
    with pytest.raises(ViewInteractionError,match='OWNER_MISMATCH'):
        s.renderer.execute(other,renderer_request(session,'inspect'))
    assert s.tokens.execute(s.renderer_raw).capabilities==frozenset({'console:renderer'})


def test_register_is_idempotent_and_has_no_owner_or_credential_in_output(system):
    a=register(system);b=register(system)
    assert a==b
    assert set(a)=={'session_id','epoch','revision','last_seen','state','online','source'}
    assert len(system.repository.sessions())==1


def test_accepted_then_reported_display_is_not_execution(system):
    s=system;session=register(s);req=request(session)
    assert s.requests.execute(s.automation,req)['status']=='accepted'
    poll=s.renderer.execute(s.renderer_raw,renderer_request(session,'poll',state=STATE))
    assert len(poll['requests'])==1
    shown={**STATE,'view':'experiment','entity_id':'run-1'}
    ack=renderer_request(session,'acknowledge',state=shown,request_id='show',outcome='displayed')
    result=s.renderer.execute(s.renderer_raw,ack)
    assert result['session']['revision']==1
    receipt=s.reads.execute(s.automation,ViewStateReadRequest('receipt','show'))
    assert receipt['status']=='displayed' and receipt['outcome']=='renderer_report'
    assert s.requests.execute(s.automation,req)['status']=='displayed'
    assert [row.resource for row in s.observation.calls]==['run']
    assert s.renderer.execute(s.renderer_raw,ack)['session']==result['session']


def test_duplicate_id_payload_change_and_stale_revision_are_rejected(system):
    s=system;session=register(s);req=request(session)
    s.requests.execute(s.automation,req)
    with pytest.raises(ViewInteractionError,match='REQUEST_CONFLICT'):
        s.requests.execute(s.automation,replace(req,entity_id='other'))
    newer=s.renderer.execute(s.renderer_raw,renderer_request(session,'poll',state={**STATE,'dirty':True}))['session']
    assert newer['revision']==1
    with pytest.raises(ViewInteractionError,match='REVISION_CONFLICT'):
        s.requests.execute(s.automation,request(session,'stale'))
    with pytest.raises(ViewInteractionError,match='REVISION_CONFLICT'):
        s.requests.execute(s.automation,request(newer,'epoch',epoch='wrong'))


def test_session_expiry_does_not_revive_or_replay(system):
    s=system;session=register(s);req=request(session)
    s.requests.execute(s.automation,req);s.clock.now+=16
    assert s.reads.execute(s.automation,ViewStateReadRequest())['sessions'][0]['online'] is False
    assert s.requests.execute(s.automation,req)['status']=='expired'
    with pytest.raises(ViewInteractionError,match='RENDERER_EXPIRED'):
        s.renderer.execute(s.renderer_raw,renderer_request(session,'poll',state=STATE))
    s.renderer_raw='Bearer '+s.tokens.issue_renderer_session();fresh=register(s)
    assert fresh['session_id']!=session['session_id'] and fresh['epoch']!=session['epoch']
    assert not s.renderer.execute(s.renderer_raw,renderer_request(fresh,'poll',state=STATE))['requests']


def test_request_expiry_and_closed_session_preserve_terminal_receipts(system):
    s=system;session=register(s);s.requests.execute(s.automation,request(session))
    s.clock.now+=10
    current=s.renderer.execute(s.renderer_raw,renderer_request(session,'poll',state=STATE))['session']
    s.renderer.execute(s.renderer_raw,renderer_request(current,'close'))
    assert s.reads.execute(s.automation,ViewStateReadRequest('receipt','show'))['status']=='expired'
    assert s.reads.execute(s.automation,ViewStateReadRequest())['sessions'][0]['online'] is False


@pytest.mark.parametrize('outcome',['deferred','rejected'])
def test_renderer_can_report_non_display_without_changing_view(system,outcome):
    s=system;session=register(s);s.requests.execute(s.automation,request(session))
    result=s.renderer.execute(s.renderer_raw,renderer_request(session,'acknowledge',state=STATE,request_id='show',outcome=outcome))
    assert result['session']['state']==STATE
    assert s.reads.execute(s.automation,ViewStateReadRequest('receipt','show'))['status']==outcome


def test_two_independent_connections_share_state_and_atomic_deduplication(system):
    s=system;session=register(s)
    other_repository=SqliteViewInteractionRepository(s.repository.path,'station')
    other_tokens=TokenInteractor(SessionCredentialRepository())
    other=ViewRequestInteractor(other_tokens,other_repository,s.observation,s.clock)
    raw='Bearer '+other_tokens.issue_automation_session()
    with ThreadPoolExecutor(2) as pool:
        values=list(pool.map(lambda _:other.execute(raw,request(session)),range(2)))
    assert all(value['status']=='accepted' for value in values)
    assert len(s.repository.pending(session['session_id'],session['epoch']))==1
    with pytest.raises(ConsoleAccessError): s.tokens.execute(raw)
    with pytest.raises(ValueError,match='STATION_MISMATCH'):
        SqliteViewInteractionRepository(s.repository.path,'other-station')


def test_unknown_ack_response_can_be_reconciled_with_renderer_inspect(system):
    s=system;session=register(s);s.requests.execute(s.automation,request(session))
    shown={**STATE,'view':'experiment','entity_id':'run-1'}
    s.renderer.execute(s.renderer_raw,renderer_request(session,'acknowledge',state=shown,request_id='show',outcome='displayed'))
    with pytest.raises(ViewInteractionError,match='REVISION_CONFLICT'):
        s.renderer.execute(s.renderer_raw,renderer_request(session,'poll',state=shown))
    reconciled=s.renderer.execute(s.renderer_raw,renderer_request(session,'inspect'))['session']
    assert reconciled['revision']==1
    assert not s.renderer.execute(s.renderer_raw,renderer_request(reconciled,'poll',state=shown))['requests']


@pytest.mark.parametrize('changes',[{'view':'https://example.com'},{'action':'eval'},{'expected_revision':True},{'request_id':'<script>'},{'view':'files','entity_id':'run-1'}])
def test_invalid_commands_never_reach_target_queries(system,changes):
    s=system;session=register(s)
    with pytest.raises(ViewInteractionError): s.requests.execute(s.automation,request(session,**changes))
    assert not s.observation.calls


def test_reveal_checks_declared_geometry_without_editing_it(system):
    s=system;session=register(s)
    assert s.requests.execute(s.automation,request(session,action='reveal',view='workstation',entity_id='plate'))['status']=='accepted'
    with pytest.raises(ViewInteractionError,match='TARGET_NOT_FOUND'):
        s.requests.execute(s.automation,request(session,'bad',action='reveal',view='workstation',entity_id='missing'))
    assert s.requests.layout_entities({'status':'available','layout':{'definition':{'collections':[{'path':'/labware','keyed':True}]},'configuration':{'labware':{'tube':{}}}}})=={'tube'}
    assert s.requests.layout_entities({'status':'available','layout':{'definition':{'collections':[{'path':['labware'],'keyed':True}]},'configuration':{'labware':{'tube':{}}}}})=={'tube'}
    assert not s.requests.layout_entities(None)


@pytest.mark.parametrize('state',[{}, {**STATE,'dirty':'yes'}, {**STATE,'view':[]}, {**STATE,'token':'secret'}])
def test_view_reports_have_a_bounded_non_authoritative_shape(state):
    with pytest.raises(ViewInteractionError): validate_view_state(state)


def test_request_expires_even_while_renderer_heartbeats(system):
    s=system;session=register(s);req=request(session)
    s.requests.execute(s.automation,req)
    for delta in [10,10,11]:
        s.clock.now+=delta
        value=s.renderer.execute(s.renderer_raw,renderer_request(session,'poll',state=STATE))
        session=value['session']
    assert session['online'] and not value['requests']
    assert s.requests.execute(s.automation,req)['status']=='expired'
    with pytest.raises(ViewInteractionError,match='ACK_EXPIRED'):
        s.renderer.execute(s.renderer_raw,renderer_request(session,'acknowledge',state=STATE,request_id='show',outcome='displayed'))


def test_read_without_renderer_does_not_create_storage_or_parent(tmp_path):
    repository=SqliteViewInteractionRepository(tmp_path/'missing'/'views.sqlite3','s')
    tokens=TokenInteractor(SessionCredentialRepository())
    reader=ViewStateReadInteractor(tokens,repository)
    assert reader.execute('Bearer '+tokens.issue_automation_session(),ViewStateReadRequest())=={'sessions':[]}
    assert repository.receipt('unknown') is None and repository.session('unknown') is None
    assert not (tmp_path/'missing').exists()


def test_heartbeat_extends_presence_without_overwriting_view_or_revision(system):
    s=system;session=register(s)
    s.clock.now+=10
    result=s.renderer.execute(s.renderer_raw,renderer_request(session,'heartbeat'))['session']
    assert result['last_seen']==s.clock.now and result['revision']==session['revision']
    assert result['state']==session['state']
    s.clock.now+=10
    assert s.reads.execute(s.automation,ViewStateReadRequest())['sessions'][0]['online']
    with pytest.raises(ViewInteractionError,match='RENDERER_REQUEST_INVALID'):
        s.renderer.execute(s.renderer_raw,renderer_request(result,'heartbeat',state={**STATE,'dirty':True}))


def test_desktop_request_is_presentation_only_and_rejects_entity_target(system):
    s=system;session=register(s)
    state=validate_view_state({**STATE,'view':'desktop'})
    assert state['view']=='desktop'
    receipt=s.requests.execute(s.automation,request(session,view='desktop',entity_id=None))
    assert receipt['status']=='accepted' and not s.observation.calls
    with pytest.raises(ViewInteractionError,match='TARGET_UNEXPECTED'):
        s.requests.execute(s.automation,request(session,'invalid-desktop',view='desktop',entity_id='run-1'))
