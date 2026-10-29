import pytest
from culsma_os.developer_tools.interactors import FaultTestInteractor, DeveloperTestInteractor
from culsma_os.developer_tools.models import FaultTestRequest
from culsma_os.driver_framework.interactors import NormalizedReceiptInteractor
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.auth.models import ConsoleAccessError


def test_unsupported_plugin_has_no_fault_probe():
    assert FaultTestInteractor(None,NormalizedReceiptInteractor()).execute('tip_unavailable')['supported'] is False


def test_only_declared_scenarios_are_admitted():
    with pytest.raises(ValueError,match='DEVELOPER_SCENARIO_INVALID'):
        FaultTestInteractor(None,NormalizedReceiptInteractor()).execute('arbitrary')


def test_protected_entry_uses_existing_permission_and_rejects_untrusted_credentials():
    tokens=TokenInteractor(SessionCredentialRepository())
    owner=DeveloperTestInteractor(tokens,None)
    assert owner.required_capability=='programs:execute'
    with pytest.raises(ConsoleAccessError):owner.execute('Bearer invalid',FaultTestRequest('tip_unavailable'))
    # A renderer session cannot execute diagnostics.
    renderer=tokens.issue_renderer_session()
    with pytest.raises(ConsoleAccessError,match='CONSOLE_CAPABILITY_DENIED'):
        owner.execute('Bearer '+renderer,FaultTestRequest('tip_unavailable'))
