import json
import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.interactors.console_session import ConsoleSessionInteractor
from tests.support.console.http import ConsoleHTTPHarness,ResidentReadFixture
from tests.support.workspace_manager.configuration import ConfigurationFixture


@pytest.fixture
def draft_console(tmp_path):
    fixture=ConfigurationFixture(tmp_path/'drafts'/'records.sqlite3')
    resident=ResidentReadFixture()
    server=ConsoleHTTPServer(ConsoleSettings(tmp_path/'missing.sock',0),ConsoleCommandInteractor(resident),
        fixture.interactor,ConsoleSessionInteractor(fixture.tokens))
    headers={'Origin':server.url,'Content-Type':'application/json','Authorization':fixture.credential}
    with ConsoleHTTPHarness(server) as harness:
        yield harness,headers,fixture,resident


def test_draft_http_flow_is_independent_of_resident(draft_console):
    console,headers,fixture,resident=draft_console
    status,_,body=console.request('GET','/api/v1/session',{'X-Culsma-Console':'1','Sec-Fetch-Site':'same-origin'})
    assert status==200 and body['scope']=='configuration:drafts'
    assert console.request('GET','/api/v1/configuration/profiles',headers)[2]['data']['profiles']
    assert console.request('GET','/api/v1/configuration/drafts',headers)[2]['data']['drafts']==[]
    code,_,body=console.request('POST','/api/v1/configuration/drafts',headers,
        {'action':'create','title':'Test draft','driver':'test-profile','configuration':{'valid':True}})
    assert code==200;draft=body['data']['draft']
    for action in ['validate','export']:
        code,_,body=console.request('POST','/api/v1/configuration/drafts',headers,
            {'action':action,'draft_id':draft['draft_id'],'revision':1})
        assert code==200 and body['data']['activation']=='not_applied'
    assert body['data']['configuration']=={'valid':True}
    code,_,body=console.request('POST','/api/v1/configuration/drafts',headers,
        {'action':'save','draft_id':draft['draft_id'],'revision':1,'title':'New','driver':'test-profile','configuration':{'valid':True}})
    assert code==200 and body['data']['draft']['revision']==2
    code,_,body=console.request('POST','/api/v1/configuration/drafts',headers,
        {'action':'validate','draft_id':draft['draft_id'],'revision':1})
    assert code==409 and body['error']['code']=='CONFIGURATION_REVISION_CONFLICT'
    assert resident.calls==[]


def test_unauthorized_draft_http_never_opens_store(draft_console):
    console,headers,fixture,resident=draft_console
    headers.pop('Authorization')
    assert console.request('GET','/api/v1/configuration/drafts',headers)[0]==401
    assert console.request('POST','/api/v1/configuration/drafts',headers,
        {'action':'create','title':'x','driver':'test-profile','configuration':{}})[0]==401
    assert not fixture.repository.path.parent.exists() and not resident.calls


@pytest.mark.parametrize('extra',[{'path':'/private/secret'},{'caller':{'role':'admin'}},{'scopes':['configuration:drafts']}])
def test_configuration_transport_rejects_unknown_fields(draft_console,extra):
    console,headers,fixture,resident=draft_console
    code,_,body=console.request('POST','/api/v1/configuration/drafts',headers,{'action':'list',**extra})
    assert code==400 and not fixture.repository.path.exists() and not resident.calls


@pytest.mark.parametrize('bootstrap_headers',[
    {}, {'X-Culsma-Console':'1'}, {'X-Culsma-Console':'1','Sec-Fetch-Site':'cross-site'},
    {'X-Culsma-Console':'1','Sec-Fetch-Site':'same-origin','Origin':'https://foreign.example'},
])
def test_session_bootstrap_rejects_foreign_or_simple_requests(draft_console,bootstrap_headers):
    console,headers,fixture,resident=draft_console
    assert console.request('GET','/api/v1/session',bootstrap_headers)[0]==403
    assert not resident.calls and not fixture.repository.path.exists()


@pytest.mark.parametrize('action',['activate','submit','pause','shutdown','reset_consumables'])
def test_configuration_channel_cannot_control_station(draft_console,action):
    console,headers,fixture,resident=draft_console
    code,_,body=console.request('POST','/api/v1/configuration/drafts',headers,{'action':action})
    assert code==400 and not resident.calls and not fixture.repository.path.exists()
