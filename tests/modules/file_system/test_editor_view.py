from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.console_interaction.repository import SqliteViewInteractionRepository
from culsma_os.console_interaction.interactors import RendererSessionInteractor,ViewRequestInteractor
from culsma_os.console_interaction.models import RendererSessionRequest,ViewRequest
from culsma_os.file_system.interactors import DocumentInspectionInteractor
from culsma_os.file_system.repository import LocalFileWorkspaceRepository


def test_mcp_can_present_an_existing_editor_without_running_it(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository());files=LocalFileWorkspaceRepository(tmp_path/'Experiments')
    files.write_document('my experiment.culs',b'let x=tube(capacity=200uL);',None)
    records=SqliteViewInteractionRepository(tmp_path/'views.sqlite3','station')
    renderer=RendererSessionInteractor(tokens,records)
    raw='Bearer '+tokens.issue_renderer_session()
    state={'view':'files','entity_id':None,'selected_entity_id':None,'dirty':False,'busy':False}
    session=renderer.execute(raw,RendererSessionRequest('register',state=state))['session']
    owner=ViewRequestInteractor(tokens,records,None,documents=DocumentInspectionInteractor(files))
    result=owner.execute('Bearer '+tokens.issue_automation_session(),ViewRequest('open','edit-test',
        session['session_id'],session['epoch'],session['revision'],'editor','my experiment.culs'))
    assert result['status']=='accepted'
    assert files.read_document('my experiment.culs')['content']=='let x=tube(capacity=200uL);'


import pytest
from culsma_os.console_interaction.models import ViewInteractionError
from culsma_os.console.adapters.mcp import MCPServerAdapter


@pytest.mark.parametrize('path',['../outside.culs','missing.culs','not-a-protocol.txt','/absolute.culs','bad\x00.culs'])
def test_invalid_editor_targets_do_not_enqueue_presentation_requests(tmp_path,path):
    tokens=TokenInteractor(SessionCredentialRepository())
    files=LocalFileWorkspaceRepository(tmp_path/'Experiments')
    records=SqliteViewInteractionRepository(tmp_path/'views.sqlite3','station')
    renderer=RendererSessionInteractor(tokens,records)
    state={'view':'files','entity_id':None,'selected_entity_id':None,'dirty':False,'busy':False}
    session=renderer.execute('Bearer '+tokens.issue_renderer_session(),RendererSessionRequest('register',state=state))['session']
    owner=ViewRequestInteractor(tokens,records,None,documents=DocumentInspectionInteractor(files))
    with pytest.raises(ViewInteractionError):
        owner.execute('Bearer '+tokens.issue_automation_session(),ViewRequest('open','invalid-editor',session['session_id'],session['epoch'],session['revision'],'editor',path))
    assert records.receipt('invalid-editor') is None


def test_ai_create_and_present_editor_retains_renderer_receipt_and_does_not_execute(tmp_path):
    from culsma_os.file_system.interactors import FileWorkspaceInteractor
    tokens=TokenInteractor(SessionCredentialRepository())
    files=LocalFileWorkspaceRepository(tmp_path/'Experiments')
    records=SqliteViewInteractionRepository(tmp_path/'views.sqlite3','station')
    renderer=RendererSessionInteractor(tokens,records)
    raw_renderer='Bearer '+tokens.issue_renderer_session()
    state={'view':'files','entity_id':None,'selected_entity_id':None,'dirty':False,'busy':False}
    session=renderer.execute(raw_renderer,RendererSessionRequest('register',state=state))['session']
    views=ViewRequestInteractor(tokens,records,None,documents=DocumentInspectionInteractor(files))
    mcp=MCPServerAdapter(None,None,None,view_requests=views,file_workspace=FileWorkspaceInteractor(tokens,files))
    mcp.raw_credential='Bearer '+tokens.issue_automation_session()
    path='experiment µ.culs'
    mcp.create_document(path,'let x=tube(capacity=200uL);return x;')
    receipt=mcp.open_view(session['session_id'],session['epoch'],session['revision'],'ai-editor','editor',path)
    assert receipt['status']=='accepted'
    shown={**state,'view':'editor','entity_id':path}
    renderer.execute(raw_renderer,RendererSessionRequest('acknowledge',session['session_id'],session['epoch'],session['revision'],state=shown,request_id='ai-editor',outcome='displayed'))
    assert records.receipt('ai-editor')['status']=='displayed'
    assert mcp.read_document(path)['content']=='let x=tube(capacity=200uL);return x;'
