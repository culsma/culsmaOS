"""Native delivery keeps the local API but exposes no browser UI or bootstrap."""
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness


def test_native_server_has_no_browser_frontend_or_browser_credential_bootstrap(tmp_path):
    settings=ConsoleSettings(tmp_path/'absent.sock',0,tmp_path/'drafts.sqlite3',serve_frontend=False)
    server=ConsoleApplicationFactory().build(settings)
    with ConsoleHTTPHarness(server) as http:
        for path in ['/', '/app.js','/console-windows.js','/style.css','/assets/culsma-logo.png','/api/v1/session']:
            assert http.request('GET',path)[0]==404
        credential=server.sessions.execute()
        status,_,body=http.request('POST','/api/v1/console/renderer',
            {'Origin':server.url,'Content-Type':'application/json','Authorization':'Bearer '+credential['renderer_access_token']},
            {'action':'register','state':{'view':'desktop','entity_id':None,'selected_entity_id':None,'dirty':False,'busy':False}})
        assert status==200 and body['data']['session']['state']['view']=='desktop'
        assert not (tmp_path/'absent.sock').exists()
