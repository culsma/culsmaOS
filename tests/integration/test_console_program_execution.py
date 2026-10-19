import sqlite3
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness, ConsoleProtocolHarness
from tests.support.integration.resident_host import ResidentHarness, GateSessionFactory
from tests.support.paths import ROOT


def session_headers(console):
    code,_,session=console.request('GET','/api/v1/session',{'X-Culsma-Console':'1','Sec-Fetch-Site':'same-origin'})
    assert code==200
    return {'Origin':console.server.url,'Content-Type':'application/json','Authorization':'Bearer '+session['access_token']}


def inspect_and_submit(console,headers,request_id='console-transfer'):
    code,_,view=console.request('POST','/api/v1/programs',headers,{'action':'inspect','program_id':'transfer.culs'})
    assert code==200 and view['data']['valid']
    payload={'action':'submit','program_id':'transfer.culs','snapshot_id':view['data']['snapshot_id'],'request_id':request_id}
    code,_,result=console.request('POST','/api/v1/programs',headers,payload)
    assert code==200 and result['data']['run']['accepted']
    return payload,result['data']['run']['run_id']


def test_console_submit_retries_create_one_run(tmp_path):
    gates=GateSessionFactory()
    resident=ResidentHarness(tmp_path,gates).start()
    server=ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint,0,
        program_root=ROOT/'examples/transfer',program_store=tmp_path/'snapshots'))
    try:
        with ConsoleHTTPHarness(server) as console:
            headers=session_headers(console)
            payload,run_id=inspect_and_submit(console,headers)
            assert gates.entered.wait(5)
            for _ in range(2):
                code,_,repeat=console.request('POST','/api/v1/programs',headers,payload)
                assert code==200 and repeat['data']['run']['run_id']==run_id
            with sqlite3.connect(resident.context.database_path) as db:
                assert db.execute('SELECT count(*) FROM os_run_queue').fetchone()[0]==1
            # No extra worker or device session is opened by console submission.
            assert len(gates.ports)==1
            gates.release.set()
            resident.wait(lambda:resident.status(run_id)['status']=='completed')
    finally:resident.stop()


def test_console_controls_preserve_unknown_head(tmp_path):
    gates=GateSessionFactory(unknown=True);gates.release.set()
    resident=ResidentHarness(tmp_path,gates).start()
    server=ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint,0,
        program_root=ROOT/'examples/transfer',program_store=tmp_path/'snapshots'))
    try:
        with ConsoleHTTPHarness(server) as console:
            headers=session_headers(console)
            payload,run_id=inspect_and_submit(console,headers)
            resident.wait(lambda:resident.status(run_id)['status']=='needs_reconciliation')
            code,_,next_run=console.request('POST','/api/v1/programs',headers,{**payload,'request_id':'next-program'})
            assert code==200
            successor=next_run['data']['run']['run_id']
            executions=len(gates.ports[0].executions)
            command={'action':'resume','run_id':run_id,'request_id':'resume-unknown'}
            for _ in range(2):assert console.request('POST','/api/v1/programs',headers,command)[0]==200
            receipt={'action':'control-status','run_id':run_id,'request_id':'resume-unknown'}
            def settled():
                code,_,view=console.request('POST','/api/v1/programs',headers,receipt)
                return code==200 and view['data']['acknowledgement']['status'] in {'applied','rejected'}
            resident.wait(settled)
            assert resident.status(run_id)['status']=='needs_reconciliation'
            assert resident.status(successor)['status']=='ready'
            assert len(gates.ports[0].executions)==executions
            with sqlite3.connect(resident.context.database_path) as db:
                assert db.execute('SELECT count(*) FROM os_run_commands').fetchone()[0]==1
    finally:resident.stop()


def test_console_submission_uses_existing_worker(tmp_path):
    with ConsoleProtocolHarness(tmp_path,'transfer') as resident:
        for index in range(2):
            server=ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint,0,
                program_root=ROOT/'examples/transfer',program_store=tmp_path/'snapshots'))
            with ConsoleHTTPHarness(server) as console:
                headers=session_headers(console)
                payload,run_id=inspect_and_submit(console,headers,f'official-transfer-{index}')
                resident.wait(lambda:any(item['run_id']==run_id and item['status']=='completed'
                    for item in resident.client.execute({'action':'runs'})['runs']),30)
                code,_,view=console.request('GET','/api/v1/runs/'+run_id)
                assert code==200
                attempts=view['data']['execution_evidence']['attempts']
                assert len(attempts)==2
                assert all(item['evidence']['outcome']=='completed' for item in attempts)
                assert all(item['registration']['status']=='registered' for item in attempts)
                containers=view['data']['result']['os']['registered_material']['state']['containers']
                assert sorted(item['volume_uL'] for item in containers.values())==[100,100]
        with sqlite3.connect(resident.database) as db:
            assert db.execute('SELECT count(*) FROM os_run_queue').fetchone()[0]==2


def test_console_pause_resume_and_cancel_have_worker_receipts(tmp_path):
    gates=GateSessionFactory()
    resident=ResidentHarness(tmp_path,gates).start()
    server=ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint,0,
        program_root=ROOT/'examples/transfer',program_store=tmp_path/'snapshots'))
    try:
        with ConsoleHTTPHarness(server) as console:
            headers=session_headers(console)
            payload,run_id=inspect_and_submit(console,headers)
            assert gates.entered.wait(5)
            pause={'action':'pause','run_id':run_id,'request_id':'pause-boundary'}
            for _ in range(2):
                code,_,receipt=console.request('POST','/api/v1/programs',headers,pause)
                assert code==200 and receipt['data']['acknowledgement']['status']=='pending'
            code,_,second=console.request('POST','/api/v1/programs',headers,{**payload,'request_id':'queued-cancel'})
            assert code==200
            successor=second['data']['run']['run_id']
            code,_,_=console.request('POST','/api/v1/programs',headers,
                {'action':'cancel','run_id':successor,'request_id':'cancel-successor'})
            assert code==200
            gates.release.set()
            resident.wait(lambda:resident.status(run_id)['status']=='paused')
            resident.wait(lambda:resident.status(successor)['status']=='cancelled')
            code,_,receipt=console.request('POST','/api/v1/programs',headers,
                {'action':'control-status','run_id':run_id,'request_id':'pause-boundary'})
            assert code==200 and receipt['data']['acknowledgement']['status']=='applied'
            # A receipt identity cannot be rebound to another run.
            assert console.request('POST','/api/v1/programs',headers,
                {'action':'control-status','run_id':successor,'request_id':'pause-boundary'})[0]==404
            assert console.request('POST','/api/v1/programs',headers,
                {'action':'resume','run_id':run_id,'request_id':'resume-boundary'})[0]==200
            resident.wait(lambda:resident.status(run_id)['status']=='completed')
            with sqlite3.connect(resident.context.database_path) as db:
                assert db.execute('SELECT count(*) FROM os_run_commands').fetchone()[0]==3
                assert db.execute("SELECT count(*) FROM os_run_commands WHERE status='applied'").fetchone()[0]==3
    finally:resident.stop()
