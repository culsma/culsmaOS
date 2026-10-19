"""Offline public plugin projection, real source compilation and console transport."""
import pytest
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.console.models import ConsoleSettings
from tests.support.console.http import ConsoleHTTPHarness
from tests.support.paths import ROOT


def test_console_binding_review_with_official_simulator_profile(tmp_path):
    profile = pytest.importorskip('culsma_opentrons.profiles').ConfigurationProfileInteractor()
    sources=tmp_path/'sources';sources.mkdir()
    (sources/'transfer.culs').write_text((ROOT/'examples/transfer/transfer.culs').read_text())
    settings=ConsoleSettings(tmp_path/'absent.sock',0,drafts_path=tmp_path/'drafts.sqlite3',
                             program_root=sources,program_store=tmp_path/'snapshots')
    server=ConsoleApplicationFactory().build(settings)
    with ConsoleHTTPHarness(server) as console:
        code,_,session=console.request('GET','/api/v1/session',{'X-Culsma-Console':'1','Sec-Fetch-Site':'same-origin'})
        assert code==200
        headers={'Origin':server.url,'Content-Type':'application/json','Authorization':'Bearer '+session['access_token']}
        code,_,created=console.request('POST','/api/v1/configuration/drafts',headers,{
            'action':'create','title':'Transfer bindings','driver':'opentrons-simulator','configuration':profile.describe()['template']})
        assert code==200
        draft=created['data']['draft']
        code,_,inspection=console.request('POST','/api/v1/programs',headers,{'action':'inspect','program_id':'transfer.culs'})
        assert code==200 and inspection['data']['valid']
        payload={'draft_id':draft['draft_id'],'revision':1,'program_id':'transfer.culs','snapshot_id':inspection['data']['snapshot_id']}
        code,_,review=console.request('POST','/api/v1/configuration/program-bindings',headers,payload)
        assert code==200 and review['data']['valid'],review
        assert [row['address']['well'] for row in review['data']['bindings']]==['A1','A2']
        configuration=draft['configuration'];del configuration['bindings']['entry.s1::alloc']
        code,_,saved=console.request('POST','/api/v1/configuration/drafts',headers,{
            'action':'save','draft_id':draft['draft_id'],'revision':1,'title':draft['title'],
            'driver':draft['driver'],'configuration':configuration})
        assert code==200
        assert console.request('POST','/api/v1/configuration/program-bindings',headers,payload)[0]==409
        payload['revision']=2
        code,_,review=console.request('POST','/api/v1/configuration/program-bindings',headers,payload)
        assert code==200 and not review['data']['valid']
        assert 'CONFIGURATION_BINDING_MISSING' in {d['code'] for d in review['data']['diagnostics']}
        assert not settings.socket_path.exists()
