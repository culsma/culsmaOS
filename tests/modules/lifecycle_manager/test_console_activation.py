from dataclasses import replace
import pytest
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.lifecycle_manager.models import ConsoleActivationRequest
from culsma_os.lifecycle_manager.interactors import ConsoleActivationInteractor
from culsma_os.workspace_manager.interactors import ConfigurationDraftInteractor
from culsma_os.workspace_manager.models import ConfigurationError
from tests.support.workspace_manager.bindings import ProgramBindingFixture


def test_activation_auth_precedes_owner_access(tmp_path,monkeypatch):
    fixture=ProgramBindingFixture(tmp_path)
    def forbidden(*args):raise AssertionError('Unauthenticated owner access')
    drafts=ConfigurationDraftInteractor(fixture.repository,fixture.profiles)
    monkeypatch.setattr(drafts,'validated',forbidden)
    interactor=ConsoleActivationInteractor(fixture.programs.tokens,drafts,fixture.programs)
    with pytest.raises(ConsoleAccessError):interactor.execute(None,ConsoleActivationRequest('apply'))
    assert not fixture.programs.calls


def test_activation_loads_exact_saved_draft_and_no_client_paths(tmp_path):
    fixture=ProgramBindingFixture(tmp_path)
    drafts=ConfigurationDraftInteractor(fixture.repository,fixture.profiles)
    interactor=ConsoleActivationInteractor(fixture.programs.tokens,drafts,fixture.programs)
    request=ConsoleActivationRequest('apply',fixture.draft['draft_id'],1,'a'*64,'request')
    interactor.execute(fixture.programs.credential,request)
    payload=fixture.programs.calls[0]
    assert payload['configuration']==fixture.configuration and payload['driver']=='fixture'
    assert set(payload['configuration_origin'])=={'draft_id','revision','title','fingerprint'}
    fixture.save(fixture.configuration)
    with pytest.raises(ConfigurationError,match='CONFIGURATION_REVISION_CONFLICT'):
        interactor.execute(fixture.programs.credential,request)
    with pytest.raises(ConfigurationError):
        interactor.execute(fixture.programs.credential,replace(request,request_id='../request'))
