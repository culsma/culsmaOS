from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.console.models import ConsoleSettings
from tests.support.console.http import ConsoleHTTPHarness


def test_files_http_requires_process_auth_and_fixed_root(tmp_path):
    root=tmp_path/'application';root.mkdir();(root/'README.txt').write_text('read me')
    server=ConsoleApplicationFactory().build(ConsoleSettings(tmp_path/'absent.sock',0,tmp_path/'drafts',program_store=tmp_path/'snapshots',file_root=root))
    with ConsoleHTTPHarness(server) as http:
        headers={'Origin':server.url,'Content-Type':'application/json'}
        assert http.request('POST','/api/v1/files',headers,{'action':'list'})[0]==401
        headers['Authorization']='Bearer '+server.sessions.tokens.issue_console_session()
        code,_,body=http.request('POST','/api/v1/files',headers,{'action':'list'})
        assert code==200 and body['data']['entries'][0]['name']=='README.txt'
        assert body['schema']=='culsma_files_v1'
        assert http.request('POST','/api/v1/files',headers,{'action':'preview','path':'../secret'})[0]==400
        assert http.request('POST','/api/v1/files',headers,{'action':'delete','path':'README.txt'})[0]==400
        assert http.request('POST','/api/v1/files',headers,{'action':'preview','path':'README.txt'})[2]['data']['content']=='read me'
