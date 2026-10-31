from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from culsma_os.auth.interactors import TokenInteractor, AuthorizedInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.lifecycle_manager.interactors import StationSelectionInteractor
from culsma_os.lifecycle_manager.models import StationSelectionRequest, StationSelectionError
from culsma_os.lifecycle_manager.repository import FileStationSelectionRepository


def system(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository())
    credential='Bearer '+tokens.issue_automation_session()
    ready=tmp_path/'installed';ready.mkdir()
    profiles=[{'id':'first','label':'First simulator','driver':'first-driver','required_paths':[str(ready)]},
              {'id':'second','label':'Second simulator','driver':'second-driver','required_paths':[str(ready)]},
              {'id':'missing','label':'Not installed','driver':'missing','required_paths':[str(tmp_path/'absent')]}]
    repository=FileStationSelectionRepository(tmp_path/'state/station.json',profiles,'first')
    owner=StationSelectionInteractor(tokens,repository,'first')
    return tokens,credential,repository,owner


def test_selection_survives_reconnect_without_touching_current_station_data(tmp_path):
    tokens,raw,repository,owner=system(tmp_path)
    data=tmp_path/'os.sqlite3';data.write_bytes(b'existing station data')
    before=owner.execute(raw,StationSelectionRequest('status'))
    assert before['selected_profile']==before['connected_profile']=='first'
    result=owner.execute(raw,StationSelectionRequest('select','second','first'))
    assert result['selected_profile']=='second' and result['connected_profile']=='first'
    assert result['restart_required'] and result['mcp_reconnect_required']
    assert result['runtime_changed'] is result['station_data_changed'] is False
    assert result['resident']=={'status':'not_observed','driver':None}
    assert data.read_bytes()==b'existing station data'
    assert json.loads(repository.path.read_text())=={'profile':'second'}
    assert repository.path.stat().st_mode & 0o777==0o600
    reconnected=StationSelectionInteractor(tokens,FileStationSelectionRepository(repository.path,repository.catalogue,'first'),'second')
    status=reconnected.execute(raw,StationSelectionRequest('status'))
    assert status['selected_profile']==status['connected_profile']=='second'
    assert not status['restart_required']
    reconnected.execute(raw,StationSelectionRequest('select','first','second'))
    assert repository.read()=='first' and data.read_bytes()==b'existing station data'


def test_unknown_uninstalled_and_stale_choices_do_not_modify_the_file(tmp_path):
    _,raw,repository,owner=system(tmp_path)
    for profile,expected,code in [('unknown','first','STATION_PROFILE_NOT_FOUND'),
                                  ('missing','first','STATION_PROFILE_NOT_INSTALLED'),
                                  ('second','stale','STATION_SELECTION_CONFLICT')]:
        with pytest.raises(StationSelectionError,match=code):owner.execute(raw,StationSelectionRequest('select',profile,expected))
        assert not repository.path.exists()
    with pytest.raises(StationSelectionError):owner.execute(raw,StationSelectionRequest('status','second'))
    with pytest.raises(ValueError):owner.execute('Bearer invalid',StationSelectionRequest('select','second','first'))
    assert not repository.path.exists()


def test_atomic_compare_and_swap_between_independent_owners(tmp_path):
    tokens,raw,repository,owner=system(tmp_path)
    other=StationSelectionInteractor(tokens,FileStationSelectionRepository(repository.path,repository.catalogue,'first'),'first')
    def select(interactor):
        try:return interactor.execute(raw,StationSelectionRequest('select','second','first'))['selected_profile']
        except StationSelectionError as error:return error.code
    with ThreadPoolExecutor(2) as executor:
        values=list(executor.map(select,[owner,other]))
    assert sorted(values)==['STATION_SELECTION_CONFLICT','second']
    assert json.loads(repository.path.read_text())=={'profile':'second'}
    assert not list(repository.path.parent.glob('.station-*'))


def test_linked_and_malformed_selection_are_rejected(tmp_path):
    _,raw,repository,owner=system(tmp_path)
    repository.path.parent.mkdir()
    outside=tmp_path/'outside.json';outside.write_text('{"profile":"first"}')
    repository.path.symlink_to(outside)
    with pytest.raises(StationSelectionError,match='STATION_SELECTION_FILE_IS_LINK'):
        owner.execute(raw,StationSelectionRequest('select','second','first'))
    assert json.loads(outside.read_text())=={'profile':'first'}
    repository.path.unlink();repository.path.write_text('[]')
    with pytest.raises(StationSelectionError,match='STATION_SELECTION_FILE_INVALID'):
        owner.execute(raw,StationSelectionRequest('status'))


def test_lifecycle_selection_uses_the_fixed_authorized_entry():
    assert StationSelectionInteractor.execute is AuthorizedInteractor.execute
    assert StationSelectionInteractor.required_capability=='configuration:activate'
