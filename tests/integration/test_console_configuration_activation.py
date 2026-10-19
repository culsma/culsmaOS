import json
import sqlite3
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness, ConsoleProtocolHarness
from tests.support.integration.resident_host import ResidentHarness, GateSessionFactory
from tests.support.paths import ROOT
from tests.support.console.programs import session_headers, inspect_and_submit


def save_draft(console,headers,configuration,title='Transfer station'):
    code,_,body=console.request('POST','/api/v1/configuration/drafts',headers,
        {'action':'create','title':title,'driver':'opentrons-simulator','configuration':configuration})
    assert code==200,body
    return body['data']['draft']


def active(console,headers):
    code,_,body=console.request('GET','/api/v1/configuration/active',headers)
    assert code==200,body
    return body['data']


def test_official_activation_preserves_history_and_tips(tmp_path):
    with ConsoleProtocolHarness(tmp_path,'transfer') as resident:
        settings=ConsoleSettings(resident.endpoint,0,tmp_path/'drafts.sqlite3',ROOT/'examples/transfer',tmp_path/'snapshots')
        with ConsoleHTTPHarness(ConsoleApplicationFactory().build(settings)) as console:
            headers=session_headers(console)
            old=active(console,headers)
            payload,first=inspect_and_submit(console,headers,'before-activation')
            resident.wait(lambda:resident.client.execute({'action':'status','run_id':first})['status']=='completed',30)
            before=resident.client.execute({'action':'device-status'})['devices'][0]['consumables']['tips']['known_consumed']
            raw=json.loads((ROOT/'examples/transfer/deck.json').read_text());raw['bindings']['entry.s1::alloc']['well']='A3'
            draft=save_draft(console,headers,raw)
            command={'action':'apply','draft_id':draft['draft_id'],'revision':1,
                     'expected_fingerprint':old['active']['fingerprint'],'request_id':'apply-transfer'}
            code,_,receipt=console.request('POST','/api/v1/configuration/activation',headers,command)
            assert code==200 and receipt['data']['status']=='accepted',receipt
            resident.wait(lambda:active(console,headers)['receipt']['status']=='applied',30)
            current=active(console,headers)
            assert current['host']['status']=='ready'
            assert current['active']['origin']['draft_id']==draft['draft_id']
            assert current['active']['fingerprint']!=old['active']['fingerprint']
            # Retrying acknowledgement returns its original durable receipt, not another worker rebuild.
            repeat=console.request('POST','/api/v1/configuration/activation',headers,command)
            assert repeat[0]==200 and repeat[2]['data']['status']=='applied'
            with sqlite3.connect(resident.database) as connection:
                assert connection.execute('SELECT count(*) FROM os_configuration_activations').fetchone()[0]==1
            stale={**payload,'request_id':'stale-program','configuration_fingerprint':old['active']['fingerprint']}
            rejected=console.request('POST','/api/v1/programs',headers,stale)
            assert rejected[0]==409 and rejected[2]['error']['code']=='HOST_CONFIGURATION_STALE',rejected
            request={**payload,'request_id':'after-activation','configuration_fingerprint':current['active']['fingerprint']}
            code,_,result=console.request('POST','/api/v1/programs',headers,request)
            assert code==200,result
            second=result['data']['run']['run_id']
            resident.wait(lambda:resident.client.execute({'action':'status','run_id':second})['status']=='completed',30)
            after=resident.client.execute({'action':'device-status'})['devices'][0]['consumables']['tips']['known_consumed']
            assert before==2 and after==4
            assert len(resident.client.execute({'action':'runs'})['runs'])==2
            evidence=resident.client.execute({'action':'run-evidence','run_id':second})
            assert all(row['registration']['status']=='registered' for row in evidence['attempts'])
            # The effective saved configuration is restored when serve restarts with its original arguments.
            resident.client.execute({'action':'shutdown'});resident.process.wait(timeout=10)
        with ConsoleProtocolHarness(tmp_path,'transfer') as restarted:
            view=restarted.client.execute({'action':'configuration-status'})
            assert view['active']['origin']['draft_id']==draft['draft_id']
            assert view['receipt']['status']=='applied'
            assert len(restarted.client.execute({'action':'runs'})['runs'])==2


def test_activation_rejects_running_and_unknown_head(tmp_path):
    gates=GateSessionFactory(unknown=True)
    resident=ResidentHarness(tmp_path,gates).start()
    try:
        run=resident.submit(request_id='blocked')['run_id']
        assert gates.entered.wait(5)
        status=resident.client.execute({'action':'configuration-status'})
        request={'action':'configure','request_id':'blocked-apply','driver':'fake','configuration':{},
                 'configuration_origin':{'draft_id':'draft','revision':1,'title':'Station','fingerprint':__import__('hashlib').sha256(b'{}').hexdigest()},
                 'configuration_fingerprint':status['active']['fingerprint']}
        import pytest
        with pytest.raises(ValueError,match='HOST_CONFIGURATION_BUSY'):resident.client.execute(request)
        gates.release.set()
        resident.wait(lambda:resident.status(run)['status']=='needs_reconciliation')
        with pytest.raises(ValueError,match='HOST_CONFIGURATION_BUSY'):resident.client.execute(request)
        assert len(gates.ports)==1
    finally:resident.stop()



def test_idle_activation_rebuilds_one_worker(tmp_path):
    from tests.support.integration.configuration_activation import RebuildSessionFixture, activation_payload
    sessions=RebuildSessionFixture();resident=ResidentHarness(tmp_path,sessions).start()
    try:
        request=activation_payload(resident,{'new':'configuration'})
        assert resident.client.execute(request)['status']=='accepted'
        resident.wait(lambda:resident.client.execute({'action':'configuration-status'})['receipt']['status']=='applied')
        assert len(sessions.ports)==2 and sessions.ports[0].closed and not sessions.ports[1].closed
        assert resident.client.execute(request)['status']=='applied'
        changed={**request,'configuration':{'different':True}}
        import pytest
        with pytest.raises(ValueError,match='HOST_CONFIGURATION_INVALID|HOST_CONFIGURATION_REQUEST_CONFLICT'):
            resident.client.execute(changed)
        stale=activation_payload(resident,{'another':True},'stale-configuration',request['configuration_fingerprint'])
        with pytest.raises(ValueError,match='HOST_CONFIGURATION_STALE'):resident.client.execute(stale)
        assert len(sessions.ports)==2
    finally:resident.stop()


def test_activation_start_failure_blocks_submissions(tmp_path):
    from tests.support.integration.configuration_activation import RebuildSessionFixture, activation_payload
    sessions=RebuildSessionFixture();resident=ResidentHarness(tmp_path,sessions).start()
    try:
        resident.client.execute(activation_payload(resident,{'fail_start':True}))
        resident.wait(lambda:resident.client.execute({'action':'configuration-status'})['receipt']['status']=='failed')
        status=resident.client.execute({'action':'configuration-status'})
        assert status['host']['status']=='failed' and sessions.ports[0].closed
        import pytest
        with pytest.raises(ValueError,match='HOST_WORKER_FAILED'):resident.submit()
        assert resident.client.execute({'action':'runs'})['runs']==[]
        # Repair is explicit; there is no automatic rollback or repeated device session.
        resident.client.execute(activation_payload(resident,{},'explicit-repair'))
        resident.wait(lambda:resident.client.execute({'action':'configuration-status'})['receipt']['status']=='applied')
        assert len(sessions.ports)==2
    finally:resident.stop()



def test_applied_pcr_configuration_runs_complete_protocol(tmp_path):
    with ConsoleProtocolHarness(tmp_path,'pcr-benchmark') as resident:
        settings=ConsoleSettings(resident.endpoint,0,tmp_path/'drafts.sqlite3',ROOT/'examples/pcr-benchmark',tmp_path/'snapshots')
        with ConsoleHTTPHarness(ConsoleApplicationFactory().build(settings)) as console:
            headers=session_headers(console)
            draft=save_draft(console,headers,json.loads((ROOT/'examples/pcr-benchmark/deck.json').read_text()),'PCR station')
            command={'action':'apply','draft_id':draft['draft_id'],'revision':1,
                     'expected_fingerprint':active(console,headers)['active']['fingerprint'],'request_id':'apply-pcr'}
            assert console.request('POST','/api/v1/configuration/activation',headers,command)[0]==200
            resident.wait(lambda:active(console,headers)['receipt']['status']=='applied',30)
            code,_,view=console.request('POST','/api/v1/programs',headers,{'action':'inspect','program_id':'protocol.culs'})
            assert code==200 and view['data']['valid'],view
            request={'action':'submit','program_id':'protocol.culs','snapshot_id':view['data']['snapshot_id'],
                     'request_id':'console-pcr','configuration_fingerprint':active(console,headers)['active']['fingerprint']}
            code,_,accepted=console.request('POST','/api/v1/programs',headers,request)
            assert code==200,accepted
            run_id=accepted['data']['run']['run_id']
            resident.wait(lambda:resident.client.execute({'action':'status','run_id':run_id})['status'] in {'completed','failed','needs_reconciliation'},90)
            assert resident.client.execute({'action':'status','run_id':run_id})['status']=='completed'
            code,_,run=console.request('GET','/api/v1/runs/'+run_id)
            assert code==200
            attempts=run['data']['execution_evidence']['attempts']
            assert len(attempts)>30 and all(row['evidence']['outcome']=='completed' for row in attempts)
            assert all(row['registration']['status']=='registered' for row in attempts)
            containers=run['data']['result']['os']['registered_material']['state']['containers']
            assert any(item['volume_uL']==50 for item in containers.values())


def test_failed_old_session_close_never_starts_replacement(tmp_path,monkeypatch):
    from tests.support.integration.configuration_activation import RebuildSessionFixture, activation_payload
    sessions=RebuildSessionFixture();resident=ResidentHarness(tmp_path,sessions).start()
    try:
        original=resident.client.execute({'action':'configuration-status'})['active']['fingerprint']
        old=sessions.ports[0]
        def fail_close():
            old.closed=True
            raise ValueError('FIXTURE_CLOSE_FAILURE')
        monkeypatch.setattr(old,'close',fail_close)
        resident.client.execute(activation_payload(resident,{},'close-failure'))
        resident.wait(lambda:resident.client.execute({'action':'configuration-status'})['receipt']['status']=='failed')
        view=resident.client.execute({'action':'configuration-status'})
        assert view['host']['status']=='failed' and view['active']['fingerprint']==original
        assert len(sessions.ports)==1
    finally:resident.stop()
