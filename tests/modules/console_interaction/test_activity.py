import json
import pytest
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.console_interaction.repository import SqliteViewInteractionRepository
from culsma_os.console_interaction.interactors import ConsoleActivityInteractor, ViewStateReadInteractor, RendererSessionInteractor
from culsma_os.console_interaction.models import ViewStateReadRequest, RendererSessionRequest
from culsma_os.file_system.interactors import FileWorkspaceInteractor
from culsma_os.file_system.repository import LocalFileWorkspaceRepository
from culsma_os.file_system.models import FileWorkspaceRequest, FileReadError


def test_real_file_change_is_visible_across_process_repositories_and_renderer_cursor(tmp_path):
    root=tmp_path/'home';root.mkdir()
    tokens=TokenInteractor(SessionCredentialRepository())
    raw='Bearer '+tokens.issue_automation_session()
    path=tmp_path/'views.sqlite3'
    repository=SqliteViewInteractionRepository(path,'station')
    owner=FileWorkspaceInteractor(tokens,LocalFileWorkspaceRepository(root))
    owner.observer=ConsoleActivityInteractor(repository)
    content='entry { }'
    created=owner.execute(raw,FileWorkspaceRequest('create','test.culs',content))
    assert (root/'test.culs').read_text()==content
    separate=SqliteViewInteractionRepository(path,'station')
    rows=ViewStateReadInteractor(tokens,separate).execute(raw,ViewStateReadRequest())['activity']
    assert [v['phase'] for v in rows]==['started','returned']
    assert all(v['actor']=='automation' and v['target']=='test.culs' for v in rows)
    assert content not in json.dumps(rows) and raw not in json.dumps(rows)
    credential='Bearer '+tokens.issue_renderer_session()
    renderer=RendererSessionInteractor(tokens,separate)
    state=dict(view='files',entity_id=None,selected_entity_id=None,dirty=False,busy=False)
    session=renderer.execute(credential,RendererSessionRequest('register',state=state))['session']
    saved=owner.execute(raw,FileWorkspaceRequest('save','test.culs','entry { /* changed */ }',created['revision']))
    result=renderer.execute(credential,RendererSessionRequest('poll',session['session_id'],session['epoch'],session['revision'],state,activity_after=rows[-1]['sequence']))
    assert [v['action'] for v in result['activity']]==['file.save','file.save']
    assert saved['revision']!=created['revision']
    assert separate.activities(result['activity'][-1]['sequence'])==[]
    with pytest.raises(FileReadError):
        owner.execute(raw,FileWorkspaceRequest('save','test.culs','stale',created['revision']))
    assert separate.activities()[-1]['phase']=='failed'
    assert separate.activities()[-1]['code']=='FILE_REVISION_CONFLICT'
    assert (root/'test.culs').read_text()=='entry { /* changed */ }'


def test_unauthorized_commands_create_no_activity_and_no_file(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository())
    root=tmp_path/'home';root.mkdir()
    repository=SqliteViewInteractionRepository(tmp_path/'views.sqlite3','station')
    owner=FileWorkspaceInteractor(tokens,LocalFileWorkspaceRepository(root))
    owner.observer=ConsoleActivityInteractor(repository)
    with pytest.raises(ValueError):owner.execute('Bearer invalid',FileWorkspaceRequest('create','test.culs','entry {}'))
    assert repository.activities()==[] and not (root/'test.culs').exists()


def test_failed_activity_storage_does_not_change_atomic_file_result(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository())
    raw='Bearer '+tokens.issue_console_session()
    root=tmp_path/'home';root.mkdir()
    path=tmp_path/'blocked';path.write_text('not a directory')
    owner=FileWorkspaceInteractor(tokens,LocalFileWorkspaceRepository(root))
    owner.observer=ConsoleActivityInteractor(SqliteViewInteractionRepository(path/'views.sqlite3','station'))
    assert owner.execute(raw,FileWorkspaceRequest('create','test.culs','entry {}'))['path']=='test.culs'
    assert (root/'test.culs').read_text()=='entry {}'
