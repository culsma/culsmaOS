import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.console_interaction.interactors import ViewStateReadInteractor, ViewRequestInteractor, RendererSessionInteractor
from culsma_os.console_interaction.repository import SqliteViewInteractionRepository
from tests.support.console.http import ConsoleHTTPHarness
from tests.support.console.view_interaction import Observation, STATE


def test_http_renderer_identity_and_transport_shape_are_checked(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository());repo=SqliteViewInteractionRepository(tmp_path/'views.sqlite3','s')
    server=ConsoleHTTPServer(ConsoleSettings(tmp_path/'host.sock',0),None,
        view_reads=ViewStateReadInteractor(tokens,repo),view_requests=ViewRequestInteractor(tokens,repo,Observation()),
        renderer_sessions=RendererSessionInteractor(tokens,repo))
    headers={'Origin':server.url,'Content-Type':'application/json','Authorization':'Bearer '+tokens.issue_renderer_session()}
    with ConsoleHTTPHarness(server) as http:
        code,_,body=http.request('POST','/api/v1/console/renderer',headers,{'action':'register','state':STATE})
        assert code==200 and body['schema']=='culsma_view_interaction_v1'
        session=body['data']['session']
        for extra in [{'caller':'owner'},{'owner':'renderer'},{'capabilities':['console:renderer']},{'token':'secret'}]:
            assert http.request('POST','/api/v1/console/renderer',headers,{'action':'register','state':STATE,**extra})[0]==400
        headers['Authorization']='Bearer '+tokens.issue_automation_session()
        assert http.request('POST','/api/v1/console/views/read',headers,{})[0]==200
        assert http.request('POST','/api/v1/console/renderer',headers,{'action':'inspect',
            'session_id':session['session_id'],'epoch':session['epoch'],'revision':0})[0]==403
        headers['Authorization']='Bearer invalid'
        assert http.request('POST','/api/v1/console/views/read',headers,{})[0]==401
