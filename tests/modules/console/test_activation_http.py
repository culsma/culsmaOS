import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.lifecycle_manager.interactors import ConsoleActivationInteractor
from culsma_os.workspace_manager.interactors import ConfigurationDraftInteractor
from tests.support.console.http import ConsoleHTTPHarness, ResidentReadFixture
from tests.support.workspace_manager.bindings import ProgramBindingFixture


@pytest.mark.parametrize('extra',[{'configuration':{}},{'config_path':'/secret'},{'caller':'admin'},{'scope':'configuration:activate'}])
def test_activation_http_rejects_authority_fields(tmp_path,extra):
    fixture=ProgramBindingFixture(tmp_path)
    interactor=ConsoleActivationInteractor(fixture.programs.tokens,
        ConfigurationDraftInteractor(fixture.repository,fixture.profiles),fixture.programs)
    server=ConsoleHTTPServer(ConsoleSettings(tmp_path/'missing.sock',0),ConsoleCommandInteractor(ResidentReadFixture()),activation=interactor)
    with ConsoleHTTPHarness(server) as console:
        headers={'Origin':server.url,'Content-Type':'application/json','Authorization':fixture.programs.credential}
        payload={'action':'apply','draft_id':fixture.draft['draft_id'],'revision':1,
                 'expected_fingerprint':'a'*64,'request_id':'request',**extra}
        code,_,body=console.request('POST','/api/v1/configuration/activation',headers,payload)
        assert code==400 and not fixture.programs.calls
