from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness


class Resident:
    def __init__(self):self.calls=[]
    def execute(self,payload):self.calls.append(payload);return {'supported':False}


def test_supply_http_uses_fixed_auth_entry_and_never_accepts_authoritative_identity(tmp_path):
    server=ConsoleApplicationFactory().build(ConsoleSettings(tmp_path/'absent.sock',0,tmp_path/'drafts.sqlite3',serve_frontend=False))
    resident=Resident();server.supplies.resident=resident
    tokens=server.sessions.tokens
    with ConsoleHTTPHarness(server) as http:
        def post(token,body):
            return http.request('POST','/api/v1/consumables',{'Origin':server.url,'Content-Type':'application/json','Authorization':'Bearer '+token},body)[0]
        human=tokens.issue_console_session();renderer=tokens.issue_renderer_session()
        assert post(renderer,{'action':'show'})==403
        assert post(human,{'action':'show','origin':'forged'})==400
        assert post(human,{'action':'replace','request_id':'box','expected_revision':'a'*64,'resource_id':'tips','positions':['1'],'simulation_acknowledged':False})==400
        assert not resident.calls
        assert post(human,{'action':'show'})==200
        assert resident.calls[0]['supply_origin']=='local-console-process'


def test_definite_resident_rejection_is_a_conflict_not_an_unknown_server_failure(tmp_path):
    from culsma_os.program_manager.models import ResidentAdmissionError
    server=ConsoleApplicationFactory().build(ConsoleSettings(tmp_path/'absent.sock',0,tmp_path/'drafts.sqlite3',serve_frontend=False))
    class Busy:
        def execute(self,payload):raise ResidentAdmissionError('HOST_NOT_IDLE')
    server.supplies.resident=Busy()
    with ConsoleHTTPHarness(server) as http:
        raw=server.sessions.tokens.issue_console_session()
        status,_,body=http.request('POST','/api/v1/consumables',{'Origin':server.url,'Content-Type':'application/json','Authorization':'Bearer '+raw},{'action':'show'})
        assert status==409 and 'HOST_NOT_IDLE' in str(body)
