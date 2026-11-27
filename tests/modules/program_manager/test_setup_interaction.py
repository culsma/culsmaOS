from copy import deepcopy
import pytest
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import SetupInteractionRequest, ConsoleProgramError
from culsma_os.program_manager.interactors.setup_interaction import SetupInteractionInteractor, SetupConfirmationInteractor


class RecordingResident:
    def __init__(self): self.calls=[]
    def execute(self,payload):
        self.calls.append(deepcopy(payload))
        return {'request_id':payload.get('request_id'),'status':'pending'}


@pytest.fixture
def shared():
    tokens=TokenInteractor(SessionCredentialRepository())
    resident=RecordingResident()
    return tokens,resident,SetupInteractionInteractor(tokens,resident),SetupConfirmationInteractor(tokens,resident)


def test_both_credentials_use_the_same_business_entry_and_authoritative_origin(shared):
    tokens,resident,operate,_=shared
    human='Bearer '+tokens.issue_console_session()
    automation='Bearer '+tokens.issue_automation_session()
    request=SetupInteractionRequest('begin','run-1','r1','a'*64)
    operate.execute(human,request)
    operate.execute(automation,request)
    assert resident.calls[0]['setup_origin']=='local-console-process'
    assert resident.calls[1]['setup_origin']=='local-mcp-process'
    assert {k:v for k,v in resident.calls[0].items() if k!='setup_origin'}=={k:v for k,v in resident.calls[1].items() if k!='setup_origin'}


def test_mcp_confirmation_uses_shared_owner_and_authoritative_origin(shared):
    tokens,resident,operate,confirmation=shared
    raw='Bearer '+tokens.issue_automation_session()
    request=SetupInteractionRequest('confirm','run-1','r1','a'*64,acknowledged=True)
    confirmation.execute(raw,request)
    assert resident.calls == [{'action':'setup-confirm','run_id':'run-1','request_id':'r1',
        'setup_fingerprint':'a'*64,'setup_acknowledged':True,'setup_origin':'local-mcp-process'}]
    with pytest.raises(ConsoleProgramError,match='SETUP_ACTION_UNSUPPORTED'):
        operate.execute(raw,request)
    assert len(resident.calls) == 1


@pytest.mark.parametrize('acknowledged', [False, None, 1, 'true'])
def test_mcp_requires_explicit_boolean_attestation(shared, acknowledged):
    tokens,resident,_,confirmation=shared
    with pytest.raises(ConsoleProgramError,match='SETUP_EXPLICIT_CONFIRMATION_REQUIRED'):
        confirmation.execute('Bearer '+tokens.issue_automation_session(),
            SetupInteractionRequest('confirm','run-1','r1','a'*64,acknowledged=acknowledged))
    assert not resident.calls


def test_renderer_cannot_confirm_loading(shared):
    tokens,resident,_,confirmation=shared
    with pytest.raises(ConsoleAccessError,match='CONSOLE_CAPABILITY_DENIED'):
        confirmation.execute('Bearer '+tokens.issue_renderer_session(),
            SetupInteractionRequest('confirm','run-1','r1','a'*64,acknowledged=True))
    assert not resident.calls


def test_authentication_and_explicit_attestation_precede_any_command(shared):
    tokens,resident,_,confirmation=shared
    request=SetupInteractionRequest('confirm','run-1','r1','a'*64)
    with pytest.raises(ConsoleAccessError): confirmation.execute(None,request)
    raw='Bearer '+tokens.issue_console_session()
    with pytest.raises(ConsoleProgramError): confirmation.execute(raw,request)
    confirmation.execute(raw,SetupInteractionRequest('confirm','run-1','r1','a'*64,acknowledged=True))
    assert resident.calls[-1]['setup_acknowledged'] is True


@pytest.mark.parametrize('invalid_request',[
    SetupInteractionRequest('revise','run-1','r1',preferences={}),
    SetupInteractionRequest('begin','../outside','r1','a'*64),
    SetupInteractionRequest('show','run-1','unexpected'),
    SetupInteractionRequest('begin','run-1','r1','a'*64,acknowledged=True),
])
def test_invalid_or_unversioned_commands_have_no_effect(shared,invalid_request):
    tokens,resident,operate,_=shared
    with pytest.raises(ConsoleProgramError): operate.execute('Bearer '+tokens.issue_console_session(),invalid_request)
    assert not resident.calls
