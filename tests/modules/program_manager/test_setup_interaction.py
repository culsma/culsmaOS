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


def test_mcp_credential_cannot_confirm_loading_even_if_the_tool_adapter_is_bypassed(shared):
    tokens,resident,operate,confirmation=shared
    raw='Bearer '+tokens.issue_automation_session()
    request=SetupInteractionRequest('confirm','run-1','r1','a'*64,acknowledged=True)
    with pytest.raises(ConsoleAccessError,match='CONSOLE_CAPABILITY_DENIED'):
        confirmation.execute(raw,request)
    with pytest.raises(ConsoleProgramError,match='SETUP_ACTION_UNSUPPORTED'):
        operate.execute(raw,request)
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
