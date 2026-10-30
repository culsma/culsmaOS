"""Actual HTTP -> authorized use case -> real experiment files (no resident)."""
import pytest
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness


@pytest.fixture
def workspace_http(tmp_path):
    programs=tmp_path/'Home/projects';programs.mkdir(parents=True)
    settings=ConsoleSettings(tmp_path/'unused.sock',0,tmp_path/'drafts.sqlite3',programs,tmp_path/'snapshots',tmp_path/'Home',serve_frontend=False)
    server=ConsoleApplicationFactory().build(settings)
    headers={'Origin':server.url,'Authorization':'Bearer '+server.sessions.tokens.issue_console_session(),'Content-Type':'application/json'}
    with ConsoleHTTPHarness(server) as harness:yield harness,headers,programs,settings


def test_http_create_read_save_conflict_and_missing_file(workspace_http):
    harness,headers,programs,settings=workspace_http
    def post(body):return harness.request('POST','/api/v1/files/workspace',headers,body)
    status,response,body=post({'action':'create','path':'actual.culs','content':'let x=tube(capacity=200uL);'})
    assert status==200 and body['schema']=='culsma_workspace_v1'
    assert response['Cache-Control']=='no-store'
    revision=body['data']['revision']
    assert post({'action':'read','path':'actual.culs'})[2]['data']['revision']==revision
    assert post({'action':'save','path':'actual.culs','content':'saved','expected_revision':revision})[0]==200
    status,_,body=post({'action':'save','path':'actual.culs','content':'stale','expected_revision':revision})
    assert status==409 and body['error']['code']=='FILE_REVISION_CONFLICT'
    assert (programs/'actual.culs').read_text()=='saved'
    assert post({'action':'read','path':'missing.culs'})[0]==404
    assert not settings.socket_path.exists()


@pytest.mark.parametrize('body',[{}, {'action':'read','path':12},{'action':'create','path':'x.culs','content':False},{'action':'receive','entries':{}},{'action':'read','path':'x.culs','caller':'admin'}])
def test_http_rejects_invalid_transport_shapes(workspace_http,body):
    harness,headers,programs,_=workspace_http
    assert harness.request('POST','/api/v1/files/workspace',headers,body)[0]==400
    assert list(programs.iterdir())==[]


@pytest.mark.parametrize('headers',[{}, {'Authorization':'Bearer invalid'},{'Origin':'https://foreign.example'},{'Sec-Fetch-Site':'cross-site'}])
def test_http_rejects_untrusted_requests_without_writing(workspace_http,headers):
    harness,valid,programs,_=workspace_http
    merged={**valid,**headers}
    if not headers:merged.pop('Authorization')
    assert harness.request('POST','/api/v1/files/workspace',merged,{'action':'create','path':'x.culs','content':'x'})[0] in {401,403}
    assert list(programs.iterdir())==[]
