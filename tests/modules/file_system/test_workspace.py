"""Actual user files, Auth Interactor, MCP adapter and language snapshots; no mocks."""
import base64
from pathlib import Path
import pytest
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.file_system.models import FileWorkspaceRequest,FileReadError
from culsma_os.file_system.repository import LocalFileWorkspaceRepository
from culsma_os.file_system.interactors import FileWorkspaceInteractor
from culsma_os.console.adapters.mcp import MCPServerAdapter

SOURCE='let sample=tube(capacity=200uL);return sample;'

@pytest.fixture
def workspace(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository())
    owner=FileWorkspaceInteractor(tokens,LocalFileWorkspaceRepository(tmp_path/'Experiments'))
    return tokens,owner,'Bearer '+tokens.issue_console_session()


def entry(path,content=SOURCE):return {'path':path,'data':base64.b64encode(content.encode()).decode()}


def test_create_read_save_and_revision_conflict_preserve_user_edits(workspace):
    _,owner,token=workspace
    created=owner.execute(token,FileWorkspaceRequest('create','test.culs',SOURCE))
    original=owner.execute(token,FileWorkspaceRequest('read','test.culs'))
    assert original['revision']==created['revision'] and original['content']==SOURCE
    saved=owner.execute(token,FileWorkspaceRequest('save','test.culs',SOURCE+'\n',original['revision']))
    assert saved['revision']!=original['revision']
    with pytest.raises(FileReadError,match='FILE_REVISION_CONFLICT'):
        owner.execute(token,FileWorkspaceRequest('save','test.culs','different',original['revision']))
    assert owner.execute(token,FileWorkspaceRequest('read','test.culs'))['content']==SOURCE+'\n'
    with pytest.raises(FileReadError,match='FILE_ALREADY_EXISTS'):
        owner.execute(token,FileWorkspaceRequest('create','test.culs','replacement'))


def test_receive_preserves_project_structure_and_rejects_collision_atomically(workspace):
    _,owner,token=workspace
    value=owner.execute(token,FileWorkspaceRequest('receive',entries=[entry('assay/main.culs'),entry('assay/helper.culs')]))
    assert value['count']==2
    assert owner.execute(token,FileWorkspaceRequest('read','assay/main.culs'))['content']==SOURCE
    with pytest.raises(FileReadError,match='FILE_ALREADY_EXISTS'):
        owner.execute(token,FileWorkspaceRequest('receive',entries=[entry('other/new.culs'),entry('assay/main.culs')]))
    assert not (owner.repository.root/'other').exists()


@pytest.mark.parametrize('path',['../escape.culs','/outside.culs','a/../b.culs','a//b.culs','.secret.culs','a\\b.culs','C:bad.culs'])
def test_paths_cannot_escape_or_name_hidden_files(workspace,path):
    _,owner,token=workspace
    with pytest.raises(FileReadError):owner.execute(token,FileWorkspaceRequest('create',path,SOURCE))


def test_symlinks_are_not_followed_on_read_write_or_receive(workspace,tmp_path):
    _,owner,token=workspace;root=owner.repository.root;root.mkdir()
    outside=tmp_path/'outside';outside.mkdir();(outside/'test.culs').write_text(SOURCE)
    (root/'linked').symlink_to(outside,target_is_directory=True)
    for request in [FileWorkspaceRequest('read','linked/test.culs'),FileWorkspaceRequest('create','linked/new.culs',SOURCE),
                    FileWorkspaceRequest('receive',entries=[entry('linked/new.culs')])]:
        with pytest.raises(FileReadError):owner.execute(token,request)
    assert not (outside/'new.culs').exists()


@pytest.mark.parametrize('entries',[[{'path':'a.culs','data':'invalid!'}],[entry('a.culs'),entry('A.culs')],
    [entry('folder'),entry('folder/child.culs')],[]])
def test_invalid_packages_leave_no_files(workspace,entries):
    _,owner,token=workspace
    with pytest.raises(FileReadError):owner.execute(token,FileWorkspaceRequest('receive',entries=entries))
    assert not owner.repository.root.exists()


def test_auth_and_renderer_cannot_bypass_write_permission(workspace):
    tokens,owner,_=workspace
    for raw in ['Bearer invalid','Bearer '+tokens.issue_renderer_session()]:
        with pytest.raises(ConsoleAccessError):owner.execute(raw,FileWorkspaceRequest('create','x.culs',SOURCE))


def test_mcp_and_human_use_same_files_and_conflict_rules(workspace):
    tokens,owner,token=workspace
    adapter=MCPServerAdapter(None,None,None,file_workspace=owner)
    adapter.raw_credential='Bearer '+tokens.issue_automation_session()
    adapter.receive_files([entry('from-ai.culs')])
    ai=adapter.read_document('from-ai.culs')
    human=owner.execute(token,FileWorkspaceRequest('read','from-ai.culs'))
    assert ai==human
    adapter.save_document('from-ai.culs',SOURCE+'\n',ai['revision'])
    with pytest.raises(FileReadError,match='FILE_REVISION_CONFLICT'):
        owner.execute(token,FileWorkspaceRequest('save','from-ai.culs','human edit',human['revision']))


def test_saved_changes_do_not_mutate_execution_snapshot(workspace,tmp_path):
    from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
    from culsma_os.program_manager.interactors.source import ProgramSourceInteractor
    from culsma_os.program_manager.interactors.compilation import CompilationInteractor
    from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
    _,owner,token=workspace
    old=owner.execute(token,FileWorkspaceRequest('create','protocol.culs',SOURCE))
    source=ProgramSourceInteractor(FileProgramSourceRepository(owner.repository.root,tmp_path/'snapshots'),CompilationInteractor(),HostedRuntimeInteractor())
    first=source.capture_program('protocol.culs')
    assert source.inspect_snapshot(first,'protocol.culs')['valid']
    owner.execute(token,FileWorkspaceRequest('save','protocol.culs',SOURCE.replace('200uL','300uL'),old['revision']))
    second=source.capture_program('protocol.culs')
    assert first.snapshot_id!=second.snapshot_id
    assert (first.directory/'protocol.culs').read_text()==SOURCE


def test_language_syntax_errors_retain_parser_source_position(workspace,tmp_path):
    from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
    from culsma_os.program_manager.interactors.source import ProgramSourceInteractor
    from culsma_os.program_manager.interactors.compilation import CompilationInteractor
    from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
    _,owner,token=workspace
    owner.execute(token,FileWorkspaceRequest('create','bad.culs','let sample = ;'))
    source=ProgramSourceInteractor(FileProgramSourceRepository(owner.repository.root,tmp_path/'snapshots'),CompilationInteractor(),HostedRuntimeInteractor())
    result=source.inspect_snapshot(source.capture_program('bad.culs'),'bad.culs')
    assert result['valid'] is False
    assert result['diagnostics'][0]['span']=={'line':1,'col':14}


@pytest.mark.parametrize('workspace_request,code',[
    (FileWorkspaceRequest('unknown','a.culs'),'FILE_REQUEST_INVALID'),
    (FileWorkspaceRequest('read','a.txt'),'FILE_DOCUMENT_TYPE_INVALID'),
    (FileWorkspaceRequest('read','a.culs',content='ignored'),'FILE_REQUEST_INVALID'),
    (FileWorkspaceRequest('receive',content='ignored',entries=[]),'FILE_REQUEST_INVALID'),
    (FileWorkspaceRequest('create','a.txt','text'),'FILE_DOCUMENT_INVALID'),
    (FileWorkspaceRequest('create','a.culs','bad\x00text'),'FILE_DOCUMENT_INVALID'),
    (FileWorkspaceRequest('create','a.culs','\ud800'),'FILE_DOCUMENT_INVALID'),
    (FileWorkspaceRequest('create','\ud800.culs',SOURCE),'FILE_PATH_INVALID'),
    (FileWorkspaceRequest('create','a.culs',SOURCE,'0'*64),'FILE_REQUEST_INVALID'),
    (FileWorkspaceRequest('save','a.culs',SOURCE),'FILE_REVISION_REQUIRED'),
    (FileWorkspaceRequest('save','a.culs',SOURCE,'G'*64),'FILE_REVISION_REQUIRED'),
    (FileWorkspaceRequest('save','a.culs',SOURCE,'0'*63),'FILE_REVISION_REQUIRED'),
])
def test_invalid_actions_and_document_fields_are_rejected_before_io(workspace,workspace_request,code):
    _,owner,token=workspace
    with pytest.raises(FileReadError) as raised:owner.execute(token,workspace_request)
    assert raised.value.code==code
    assert not owner.repository.root.exists()


def test_utf8_document_limit_counts_bytes_and_accepts_boundary(workspace):
    _,owner,token=workspace
    text='µ'*125000
    owner.execute(token,FileWorkspaceRequest('create','limit.culs',text))
    assert owner.execute(token,FileWorkspaceRequest('read','limit.culs'))['content']==text
    with pytest.raises(FileReadError,match='FILE_DOCUMENT_INVALID'):
        owner.execute(token,FileWorkspaceRequest('create','large.culs',text+'a'))
    assert not (owner.repository.root/'large.culs').exists()


@pytest.mark.parametrize('entries,code',[
    ([entry('a.culs')]*201,'FILE_RECEIVE_INVALID'),
    ([{'path':'a.culs','data':12}],'FILE_RECEIVE_TOO_LARGE'),
    ([{'path':'a.culs','data':'YQ==','extra':True}],'FILE_RECEIVE_INVALID'),
    ([entry('X/a.culs'),entry('x/A.culs')],'FILE_RECEIVE_DUPLICATE'),
    ([entry('Folder'),entry('folder/child.culs')],'FILE_RECEIVE_INVALID'),
])
def test_package_limits_and_case_insensitive_collisions(workspace,entries,code):
    _,owner,token=workspace
    with pytest.raises(FileReadError) as raised:
        owner.execute(token,FileWorkspaceRequest('receive',entries=entries))
    assert raised.value.code==code
    assert not owner.repository.root.exists()


def test_receive_validates_composed_destination_path_before_io(workspace):
    _,owner,token=workspace
    with pytest.raises(FileReadError,match='FILE_PATH_INVALID'):
        owner.execute(token,FileWorkspaceRequest('receive','a'*230,entries=[entry('long-name.culs')]))
    assert not owner.repository.root.exists()


def test_package_byte_limit_and_non_ascii_subdirectory_copy(workspace):
    _,owner,token=workspace
    encoded=__import__('base64').b64encode(b'x'*2000001).decode()
    with pytest.raises(FileReadError,match='FILE_RECEIVE_TOO_LARGE'):
        owner.execute(token,FileWorkspaceRequest('receive',entries=[{'path':'a.csv','data':encoded},{'path':'b.csv','data':encoded}]))
    assert not owner.repository.root.exists()
    owner.execute(token,FileWorkspaceRequest('receive',entries=[entry('assay µ/main.culs'),entry('assay µ/data.csv','x,y\n1,2')]))
    assert owner.execute(token,FileWorkspaceRequest('read','assay µ/main.culs'))['content']==SOURCE
    assert (owner.repository.root/'assay µ/data.csv').read_text()=='x,y\n1,2'


def test_revoked_automation_credential_cannot_write(workspace):
    tokens,owner,_=workspace
    raw='Bearer '+tokens.issue_automation_session()
    # Revocation uses the Auth-owned credential repository, not a fabricated caller.
    tokens.repository.store_automation(None)
    with pytest.raises(ConsoleAccessError):owner.execute(raw,FileWorkspaceRequest('create','x.culs',SOURCE))
    assert not owner.repository.root.exists()
