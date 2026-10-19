import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.interactors.console_session import ConsoleSessionInteractor
from tests.support.console.http import ConsoleHTTPHarness, ResidentReadFixture
from tests.support.program_manager.console_program import ProgramCommandFixture


@pytest.fixture
def console_programs(tmp_path):
    fixture=ProgramCommandFixture(tmp_path)
    reads=ResidentReadFixture()
    server=ConsoleHTTPServer(ConsoleSettings(tmp_path/'missing.sock',0),ConsoleCommandInteractor(reads),
        sessions=ConsoleSessionInteractor(fixture.tokens),programs=fixture.interactor)
    headers={'Origin':server.url,'Content-Type':'application/json','Authorization':fixture.credential}
    with ConsoleHTTPHarness(server) as console:yield console,headers,fixture


def test_program_http_selection_inspection_and_submission(console_programs):
    console,headers,fixture=console_programs
    code,_,body=console.request('GET','/api/v1/programs',headers)
    assert code==200 and body['data']['programs']==[{'program_id':'transfer.culs'}]
    code,_,body=console.request('POST','/api/v1/programs',headers,{'action':'inspect','program_id':'transfer.culs'})
    assert code==200 and body['data']['valid']
    snapshot=body['data']['snapshot_id']
    code,_,body=console.request('POST','/api/v1/programs',headers,
        {'action':'submit','program_id':'transfer.culs','snapshot_id':snapshot,'request_id':'same-id'})
    assert code==200 and body['data']['run']['accepted']
    assert len(fixture.calls)==1


@pytest.mark.parametrize('extra',[{'source':'/private/secret'},{'library_roots':['/']},{'caller':'admin'},{'scope':'programs:execute'}])
def test_program_transport_rejects_authority_fields(console_programs,extra):
    console,headers,fixture=console_programs
    assert console.request('POST','/api/v1/programs',headers,{'action':'list',**extra})[0]==400
    assert not fixture.calls and not fixture.sources.store.exists()


@pytest.mark.parametrize('change',[{'Authorization':''},{'Origin':'https://foreign.example'},{'Origin':''}])
def test_untrusted_program_writes_have_no_effect(console_programs,change):
    console,headers,fixture=console_programs
    headers.update(change)
    assert console.request('POST','/api/v1/programs',headers,{'action':'inspect','program_id':'transfer.culs'})[0] in {401,403}
    assert not fixture.calls and not fixture.sources.store.exists()


def test_program_diagnostics_and_disconnect_are_visible(console_programs):
    console,headers,fixture=console_programs
    fixture.failure=OSError('sensitive internal path')
    code,_,body=console.request('POST','/api/v1/programs',headers,{'action':'pause','run_id':'run-1','request_id':'r'})
    assert code==503 and body['error']['code']=='PROGRAM_HOST_RESPONSE_UNAVAILABLE'
    assert 'sensitive' not in str(body)
