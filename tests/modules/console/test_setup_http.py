import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.program_manager.interactors.setup_interaction import SetupInteractionInteractor, SetupConfirmationInteractor
from tests.support.console.http import ConsoleHTTPHarness


class SetupResident:
    def __init__(self): self.calls=[]
    def execute(self,payload):
        self.calls.append(payload)
        return {'status':'pending','request_id':payload.get('request_id')}


@pytest.fixture
def server(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository());resident=SetupResident()
    server=ConsoleHTTPServer(ConsoleSettings(tmp_path/'missing.sock',0),None,
        setup=SetupInteractionInteractor(tokens,resident),setup_confirmation=SetupConfirmationInteractor(tokens,resident))
    headers={'Origin':server.url,'Content-Type':'application/json','Authorization':'Bearer '+tokens.issue_console_session()}
    with ConsoleHTTPHarness(server) as http: yield http,headers,resident,tokens


def test_http_and_mcp_protect_physical_confirmation_with_the_same_auth_owner(server):
    http,headers,resident,tokens=server
    body={'action':'begin','run_id':'run-1','request_id':'r1','fingerprint':'a'*64}
    assert http.request('POST','/api/v1/setup',headers,body)[0]==200
    body.update(action='confirm',acknowledged=True)
    assert http.request('POST','/api/v1/setup/confirmation',headers,body)[0]==200
    headers['Authorization']='Bearer '+tokens.issue_automation_session()
    assert http.request('POST','/api/v1/setup/confirmation',headers,body)[0]==403
    assert len(resident.calls)==2


@pytest.mark.parametrize('extra',[{'origin':'human'},{'caller':'admin'},{'capabilities':['setup:confirm']},{'token':'secret'}])
def test_transport_rejects_authority_and_origin_in_request_arguments(server,extra):
    http,headers,resident,_=server
    assert http.request('POST','/api/v1/setup',headers,{'action':'show','run_id':'run-1',**extra})[0]==400
    assert not resident.calls
