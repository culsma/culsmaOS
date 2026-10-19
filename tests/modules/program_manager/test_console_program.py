from pathlib import Path
from types import SimpleNamespace
import pytest
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import ConsoleProgramRequest, ConsoleProgramError, ResidentAdmissionError
from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
from tests.support.program_manager.console_program import ProgramCommandFixture


@pytest.fixture
def programs(tmp_path): return ProgramCommandFixture(tmp_path)


def test_program_auth_precedes_source_access(programs):
    with pytest.raises(ConsoleAccessError): programs.interactor.execute(None,ConsoleProgramRequest('inspect','transfer.culs'))
    assert not programs.sources.store.exists() and programs.calls==[]


def test_source_check_shows_scope_and_allocation_identities(programs):
    view=programs.interactor.execute(programs.credential,ConsoleProgramRequest('inspect','transfer.culs'))
    assert view['valid'] and view['configuration']=='running_service'
    assert 'resident worker' in view['scope']
    assert [item['name'] for item in view['allocations']]==['source','destination']
    assert 'Mutation' in view['operations'] and programs.calls==[]


def test_submit_uses_reviewed_snapshot(programs):
    view=programs.interactor.execute(programs.credential,ConsoleProgramRequest('inspect','transfer.culs'))
    original=programs.source.read_text()
    programs.source.unlink()
    request=ConsoleProgramRequest('submit','transfer.culs',view['snapshot_id'],'request-1')
    result=programs.interactor.execute(programs.credential,request)
    assert result['effect']=='admitted_to_resident_queue'
    assert Path(programs.calls[0]['source']).read_text()==original
    assert programs.calls[0]['request_id']=='request-1'
    assert programs.calls[0]['library_roots']==[str(programs.sources.store/view['snapshot_id'])]


@pytest.mark.parametrize('program_id',['../outside.culs','/etc/passwd','transfer.culs/../../x','x\\y.culs','./x.culs'])
def test_program_root_containment(programs,program_id):
    with pytest.raises(ConsoleProgramError): programs.interactor.execute(programs.credential,ConsoleProgramRequest('inspect',program_id))
    assert not programs.calls


def test_symlink_source_and_parent_are_never_followed(programs,tmp_path):
    outside=tmp_path/'outside.culs';outside.write_text('secret')
    (programs.root/'linked.culs').symlink_to(outside)
    with pytest.raises(ConsoleProgramError):programs.sources.capture()
    (programs.root/'linked.culs').unlink()
    (programs.root/'linked').symlink_to(tmp_path,target_is_directory=True)
    assert programs.sources.source_ids()==['transfer.culs']
    with pytest.raises(ConsoleProgramError):programs.sources.read_file(programs.root,'linked/outside.culs')


def test_snapshot_tampering_rejected(programs):
    view=programs.interactor.execute(programs.credential,ConsoleProgramRequest('inspect','transfer.culs'))
    (programs.sources.store/view['snapshot_id']/'transfer.culs').write_text('changed')
    with pytest.raises(ConsoleProgramError,match='PROGRAM_SNAPSHOT_CHANGED'):
        programs.interactor.execute(programs.credential,ConsoleProgramRequest('submit','transfer.culs',view['snapshot_id'],'request-2'))
    assert programs.calls==[]


def test_library_bounds_and_opt_in(programs,tmp_path):
    programs.sources.max_file_bytes=5
    with pytest.raises(ConsoleProgramError,match='PROGRAM_SOURCE_TOO_LARGE'):programs.sources.capture()
    assert not programs.sources.store.exists()
    disabled=FileProgramSourceRepository(None,tmp_path/'other-store')
    assert disabled.list()=={'enabled':False,'programs':[]}
    programs.interactor.sources=disabled
    with pytest.raises(ConsoleProgramError,match='PROGRAM_LIBRARY_DISABLED'):
        programs.interactor.execute(programs.credential,ConsoleProgramRequest('submit','transfer.culs','a'*64,'r'))


def test_nested_imports_use_only_captured_library(programs):
    programs.source.write_text('import library;\nlet source = tube(capacity = 200uL);')
    (programs.root/'library.culs').write_text('protocol helper() {}')
    snapshot=programs.sources.capture()
    # Import containment is independent of whether a library exports runnable semantics.
    programs.interactor.validate_imports(snapshot,'transfer.culs')


@pytest.mark.parametrize('name',['../outside','/absolute','folder/../../outside'])
def test_import_containment(programs,name,monkeypatch):
    monkeypatch.setattr('culsma_os.program_manager.interactors.console_program.parse_file',
        lambda path:SimpleNamespace(library_imports=[SimpleNamespace(name=name)]))
    snapshot=programs.sources.capture()
    with pytest.raises(ConsoleProgramError,match='PROGRAM_IMPORT_OUTSIDE_LIBRARY'):
        programs.interactor.validate_imports(snapshot,'transfer.culs')


def test_compile_errors_are_diagnostic_and_cannot_submit(programs):
    programs.source.write_text('this is not a program !!!')
    view=programs.interactor.execute(programs.credential,ConsoleProgramRequest('inspect','transfer.culs'))
    assert not view['valid'] and view['diagnostics'][0]['code']=='PROGRAM_COMPILE_FAILED'
    with pytest.raises(ConsoleProgramError,match='PROGRAM_DIAGNOSTICS_REJECTED'):
        programs.interactor.execute(programs.credential,ConsoleProgramRequest('submit','transfer.culs',view['snapshot_id'],'r'))
    assert programs.calls==[]


@pytest.mark.parametrize('action',['pause','resume','cancel'])
def test_program_control_reuses_resident_queue(programs,action):
    result=programs.interactor.execute(programs.credential,ConsoleProgramRequest(action,request_id='same-request',run_id='run-1'))
    assert result['effect']=='queued_control_request'
    assert programs.calls==[{'action':action,'run_id':'run-1','request_id':'same-request'}]
    assert not programs.sources.store.exists()


def test_admission_errors_keep_codes_and_diagnostics(programs):
    programs.failure=ResidentAdmissionError('HOST_PLAN_UNSUPPORTED',[{'code':'HOST_OPERATION_UNSUPPORTED'}])
    with pytest.raises(ConsoleProgramError) as captured:
        programs.interactor.execute(programs.credential,ConsoleProgramRequest('pause',request_id='r',run_id='run-1'))
    assert captured.value.code=='HOST_PLAN_UNSUPPORTED'
    assert captured.value.diagnostics==({'code':'HOST_OPERATION_UNSUPPORTED'},)


@pytest.mark.parametrize('command',[
 ConsoleProgramRequest('shutdown'),ConsoleProgramRequest('submit','transfer.culs'),
 ConsoleProgramRequest('list',run_id='r'),ConsoleProgramRequest('inspect','transfer.culs',request_id='r'),
 ConsoleProgramRequest('resume',request_id='../x',run_id='r')])
def test_unrelated_or_malformed_commands_are_rejected(programs,command):
    with pytest.raises(ConsoleProgramError):programs.interactor.execute(programs.credential,command)
    assert not programs.calls and not programs.sources.store.exists()


def test_concurrent_source_snapshots_converge(programs):
    from concurrent.futures import ThreadPoolExecutor
    other=FileProgramSourceRepository(programs.root,programs.sources.store)
    with ThreadPoolExecutor(max_workers=2) as workers:
        snapshots=list(workers.map(lambda repository:repository.capture(),[programs.sources,other]))
    assert snapshots[0]==snapshots[1]
    assert programs.sources.load(snapshots[0].snapshot_id)==snapshots[0]
