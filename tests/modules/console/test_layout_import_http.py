from copy import deepcopy
import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.interactors.console_session import ConsoleSessionInteractor
from culsma_os.device_manager.interactors import DeviceProfileInteractor
from tests.support.console.http import ConsoleHTTPHarness,ResidentReadFixture
from tests.support.workspace_manager.configuration import ConfigurationFixture
from tests.support.device_manager.layout_import import ExternalProfile,Discovery,source,report


@pytest.fixture
def importer(tmp_path):
    fixture=ConfigurationFixture(tmp_path/'drafts.sqlite3');profile=ExternalProfile()
    fixture.interactor.profiles=DeviceProfileInteractor(Discovery(profile))
    resident=ResidentReadFixture()
    server=ConsoleHTTPServer(ConsoleSettings(tmp_path/'missing.sock',0),ConsoleCommandInteractor(resident),
        fixture.interactor,ConsoleSessionInteractor(fixture.tokens))
    headers={'Origin':server.url,'Content-Type':'application/json','Authorization':fixture.credential}
    with ConsoleHTTPHarness(server) as harness:yield harness,headers,fixture,profile,resident


def test_import_is_authorized_preview_and_never_changes_drafts_or_resident(importer):
    console,headers,fixture,profile,resident=importer
    body={'driver':'external','layout_source':source()}
    assert console.request('POST','/api/v1/configuration/layout-import',headers,body)[2]['data']['import_report']==report()
    assert not fixture.repository.list() and not resident.calls
    assert profile.calls==[(b'native bytes','layout.bin')]
    forged={**headers,'Authorization':'Bearer forged'}
    assert console.request('POST','/api/v1/configuration/layout-import',forged,body)[0]==401
    assert len(profile.calls)==1
    automation={**headers,'Authorization':'Bearer '+fixture.tokens.issue_automation_session()}
    assert console.request('POST','/api/v1/configuration/layout-import',automation,body)[0]==200
    renderer={**headers,'Authorization':'Bearer '+fixture.tokens.issue_renderer_session()}
    assert console.request('POST','/api/v1/configuration/layout-import',renderer,body)[0]==403
    assert len(profile.calls)==2


def test_native_upload_limit_does_not_expand_configuration_write_limit(importer):
    console,headers,fixture,profile,resident=importer
    content=b'x'*342490;profile.result=report(content)
    body={'driver':'external','layout_source':source(content)}
    assert console.request('POST','/api/v1/configuration/layout-import',headers,body)[0]==200
    assert console.request('POST','/api/v1/configuration/drafts',headers,body)[0]==400
    assert not fixture.repository.list() and not resident.calls


@pytest.mark.parametrize('extra',[{'path':'/private/native.lay'},{'configuration':{}},{'action':'create'}])
def test_transport_accepts_bytes_not_server_paths_or_alternate_actions(importer,extra):
    console,headers,_,profile,_=importer
    body={'driver':'external','layout_source':source(),**extra}
    assert console.request('POST','/api/v1/configuration/layout-import',headers,body)[0]==400
    assert not profile.calls
