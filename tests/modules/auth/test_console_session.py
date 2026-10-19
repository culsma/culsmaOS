import pytest
from culsma_os.auth.interactors import TokenInteractor, AuthorizedInteractor
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.auth.repository import SessionCredentialRepository


def test_process_session_is_stable_but_not_valid_in_another_process_owner():
    first=TokenInteractor(SessionCredentialRepository());second=TokenInteractor(SessionCredentialRepository())
    token=first.issue_console_session()
    assert token==first.issue_console_session()
    caller=first.execute('Bearer '+token)
    assert caller.capabilities==frozenset({'configuration:drafts','configuration:activate','programs:execute'})
    with pytest.raises(ConsoleAccessError): second.execute('Bearer '+token)
    with pytest.raises((AttributeError,TypeError)): caller.subject='forged'


def test_authorized_entry_cannot_be_overridden_or_omit_capability():
    with pytest.raises(TypeError):
        class MissingCapability(AuthorizedInteractor): pass
    with pytest.raises(TypeError):
        class Override(AuthorizedInteractor):
            required_capability='configuration:drafts'
            def execute(self,raw,request): pass
