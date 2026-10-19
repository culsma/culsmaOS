import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from tests.support.console.http import ConsoleHTTPHarness, ResidentReadFixture
from tests.support.workspace_manager.bindings import ProgramBindingFixture


@pytest.fixture
def binding_console(tmp_path):
    fixture=ProgramBindingFixture(tmp_path)
    server=ConsoleHTTPServer(ConsoleSettings(tmp_path/'absent.sock',0),ConsoleCommandInteractor(ResidentReadFixture()),bindings=fixture.interactor)
    headers={'Origin':server.url,'Content-Type':'application/json','Authorization':fixture.programs.credential}
    with ConsoleHTTPHarness(server) as console:yield console,headers,fixture


def test_binding_http_delegates_one_protected_use_case(binding_console):
    console,headers,fixture=binding_console
    code,_,body=console.request('POST','/api/v1/configuration/program-bindings',headers,vars(fixture.request))
    assert code==200 and body['data']['valid'] and body['data']['activation']=='not_applied'
    assert not fixture.programs.calls
    headers.pop('Authorization')
    assert console.request('POST','/api/v1/configuration/program-bindings',headers,vars(fixture.request))[0]==401


@pytest.mark.parametrize('extra',[{'caller':'admin'},{'configuration':{}},{'source':'/secret'},{'revision':'1'}])
def test_binding_transport_rejects_untrusted_fields(binding_console,extra):
    console,headers,fixture=binding_console
    assert console.request('POST','/api/v1/configuration/program-bindings',headers,{**vars(fixture.request),**extra})[0]==400
    assert not fixture.programs.calls
