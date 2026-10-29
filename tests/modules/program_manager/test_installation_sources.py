from pathlib import Path
from types import SimpleNamespace
import pytest
from culsma_os.program_manager.interactors.source import ProgramSourceInteractor
from culsma_os.program_manager.models import ConsoleProgramRequest,ConsoleProgramError
from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
from tests.support.program_manager.console_program import ProgramCommandFixture


def test_installation_executes_selected_snapshot_without_scanning_other_files(tmp_path):
    f=ProgramCommandFixture(tmp_path)
    selected=FileProgramSourceRepository(f.root,f.root/'artifacts',selected_only=True)
    source=ProgramSourceInteractor(selected,f.source_interactor.compilation,f.source_interactor.semantics,selected_only=True)
    f.interactor.scopes['installation']=source
    (f.root/'unrelated.culs').write_text('x'*300000)
    request=ConsoleProgramRequest('inspect','transfer.culs',source_scope='installation')
    view=f.interactor.execute(f.credential,request)
    assert view['valid']
    snapshot=selected.load(view['snapshot_id'])
    assert snapshot.files==('transfer.culs',)
    original=f.source.read_text();f.source.unlink()
    f.interactor.execute(f.credential,ConsoleProgramRequest('start','transfer.culs',view['snapshot_id'],'run-install',source_scope='installation'))
    assert Path(f.calls[0]['source']).read_text()==original
    with pytest.raises(ConsoleProgramError):f.interactor.execute(f.credential,ConsoleProgramRequest('start','transfer.culs',view['snapshot_id'],'wrong-scope'))


def test_installation_snapshot_includes_import_closure_only(tmp_path):
    f=ProgramCommandFixture(tmp_path)
    f.source.write_text('import library;\nlet source = tube(capacity = 200uL);')
    (f.root/'library.culs').write_text('protocol helper() {}')
    repo=FileProgramSourceRepository(f.root,f.root/'state',selected_only=True)
    owner=ProgramSourceInteractor(repo,f.source_interactor.compilation,f.source_interactor.semantics,selected_only=True)
    snapshot=owner.capture_program('transfer.culs')
    assert set(snapshot.files)=={'transfer.culs','library.culs'}
    owner.validate_imports(snapshot,'transfer.culs')
    assert not (f.root/'state').is_symlink()


def test_invalid_scope_never_reaches_resident(tmp_path):
    f=ProgramCommandFixture(tmp_path)
    for scope in (None,[],{},'outside'):
        with pytest.raises(ConsoleProgramError):f.interactor.execute(f.credential,ConsoleProgramRequest('inspect','transfer.culs',source_scope=scope))
    assert f.calls==[]
