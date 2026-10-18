from tests.support.paths import ROOT
from pathlib import Path
import ast
import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from uuid import uuid4
import pytest
from culsma_os.bootstrap import OSApplicationFactory, HostLeaseFactory
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter, ResidentProtocolAdapter
from culsma_os.program_manager.repositories.runs import SqliteTaskRepository
from culsma_os.program_manager.repositories.queue import SqliteRunQueueRepository
from culsma_os.program_manager.interactors.run_state import RunStateInteractor
from culsma_os.program_manager.interactors.runs import TaskInteractor
from culsma_os.program_manager.interactors.preparation import PreparationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.models import QueueSubmission
from tests.support.common import FakeSessionFactory, FakeDevicePort, ProgramFixture
from tests.support.integration.resident_host import ROOT, GatePort, GateSessionFactory, ResidentHarness


class TestResidentHost:
    def test_admission_freezes_program_and_is_idempotent(self, tmp_path):
        sessions = GateSessionFactory()
        harness = ResidentHarness(tmp_path, sessions).start()
        try:
            source = tmp_path/'protocol.culs'
            source.write_text(ProgramFixture.source.read_text())
            accepted = harness.submit(source=str(source),request_id='stable-submission')
            run_id = accepted['run_id']
            assert sessions.entered.wait(5)
            assert harness.submit(source=str(source),request_id='stable-submission')['run_id'] == run_id
            source.write_text(source.read_text().replace('50uL','25uL'))
            with pytest.raises(ValueError,match='HOST_SUBMISSION_ID_CONFLICT'):
                harness.submit(source=str(source),request_id='stable-submission')
            source.unlink()
            sessions.release.set()
            harness.wait(lambda:harness.status(run_id)['status']=='completed')
            assert len(sessions.ports[0].executions)==2
            assert len(harness.client.execute({'action':'runs'})['runs'])==1
            with sqlite3.connect(harness.context.database_path) as conn:
                assert conn.execute('SELECT count(*) FROM os_run_queue').fetchone()[0]==1
        finally:
            harness.stop()

    def test_atomic_admission_rolls_back_run_if_queue_insert_fails(self,tmp_path):
        conn=sqlite3.connect(tmp_path/'os.sqlite3')
        tasks_repo=SqliteTaskRepository(conn)
        queue=SqliteRunQueueRepository(conn)
        host=HostedRuntimeInteractor()
        tasks=TaskInteractor(tasks_repo,PreparationInteractor(host),RunStateInteractor(tasks_repo,host,None))
        submission=QueueSubmission('same','fingerprint','source')
        tasks.submit(ProgramFixture.request(),submission)
        with pytest.raises(sqlite3.IntegrityError):
            tasks.submit(ProgramFixture.request(),submission)
        assert conn.execute('SELECT count(*) FROM os_runs').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM os_run_outbox').fetchone()[0]==1
        conn.close()

    def test_resident_lease_excludes_embedded_and_other_hosts(self,tmp_path):
        harness=ResidentHarness(tmp_path).start()
        try:
            for context in (harness.context,HostBuildContext(tmp_path/'other.sqlite3','fake',None,tmp_path/'out')):
                lease=HostLeaseFactory().build(context)
                with pytest.raises(ValueError,match='HOST_ALREADY_RUNNING'):
                    lease.acquire()
            with pytest.raises(ValueError,match='HOST_ALREADY_RUNNING'):
                OSApplicationFactory({'fake':harness.sessions}).build_program_runner().execute_pipeline(
                    [ProgramFixture.source],driver_name='fake',host_database_path=harness.context.database_path)
            assert len(harness.sessions.ports)==1
        finally:
            harness.stop()
        lease=HostLeaseFactory().build(harness.context)
        lease.acquire()
        lease.close()

    def test_slow_device_does_not_block_status_and_control(self,tmp_path):
        sessions=GateSessionFactory()
        harness=ResidentHarness(tmp_path,sessions).start()
        try:
            run_id=harness.submit()['run_id']
            assert sessions.entered.wait(5)
            started=time.monotonic()
            assert harness.status(run_id)['status']=='waiting'
            command=harness.client.execute({'action':'pause','run_id':run_id})
            assert command['status']=='pending'
            assert time.monotonic()-started<1
            second=harness.submit()['run_id']
            assert harness.status(second)['status']=='ready'
            sessions.release.set()
            harness.wait(lambda:harness.status(run_id)['status']=='paused')
            assert len(sessions.ports[0].executions)==1
            assert len(harness.status(second)['result']['os'].get('registered_material',{}))==0
            harness.client.execute({'action':'resume','run_id':run_id})
            harness.wait(lambda:harness.status(second)['status']=='completed')
            assert harness.status(run_id)['status']=='completed'
            assert len(sessions.ports)==1
            assert len(sessions.ports[0].executions)==4
        finally:
            harness.stop()

    def test_unknown_head_blocks_following_protocol(self,tmp_path):
        sessions=GateSessionFactory(unknown=True)
        sessions.release.set()
        harness=ResidentHarness(tmp_path,sessions).start()
        try:
            first=harness.submit()['run_id']
            second=harness.submit()['run_id']
            harness.wait(lambda:harness.status(first)['status']=='needs_reconciliation')
            time.sleep(0.08)
            assert harness.status(second)['status']=='ready'
            assert len(sessions.ports[0].executions)==1
            assert harness.client.execute({'action':'host-status'})['blocked_run']==first
        finally:
            harness.stop()

    def test_restart_retains_queue_and_does_not_replay_unknown(self,tmp_path):
        sessions=GateSessionFactory(crash=True)
        harness=ResidentHarness(tmp_path,sessions).start()
        try:
            first=harness.submit()['run_id']
            assert sessions.entered.wait(5)
            second=harness.submit()['run_id']
            sessions.release.set()
            harness.wait(lambda:harness.client.execute({'action':'host-status'})['status']=='failed')
            with pytest.raises(ValueError,match='HOST_WORKER_FAILED'):
                harness.submit()
        finally:
            harness.stop()
        restarted_sessions=FakeSessionFactory()
        restarted=ResidentHarness(tmp_path,restarted_sessions).start()
        try:
            restarted.wait(lambda:restarted.status(first)['status']=='needs_reconciliation')
            assert restarted.status(second)['status']=='ready'
            assert not restarted_sessions.ports[0].executions
        finally:
            restarted.stop()

    def test_shutdown_pauses_at_boundary_and_retains_queued_work(self,tmp_path):
        sessions=GateSessionFactory()
        harness=ResidentHarness(tmp_path,sessions).start()
        first=harness.submit()['run_id']
        assert sessions.entered.wait(5)
        second=harness.submit()['run_id']
        assert harness.client.execute({'action':'shutdown'})['accepted']
        with pytest.raises(ValueError,match='HOST_STOPPING'):
            harness.submit()
        harness.stop()
        assert len(sessions.ports[0].executions)==1
        restarted=ResidentHarness(tmp_path).start()
        try:
            assert restarted.status(first)['status']=='paused'
            assert restarted.status(second)['status']=='ready'
            restarted.client.execute({'action':'resume','run_id':first})
            restarted.wait(lambda:restarted.status(second)['status']=='completed')
            assert restarted.status(first)['status']=='completed'
            assert len(restarted.sessions.ports[0].executions)==3
        finally:
            restarted.stop()

    def test_cancel_queued_run_does_not_dispatch_it(self,tmp_path):
        sessions=GateSessionFactory()
        harness=ResidentHarness(tmp_path,sessions).start()
        try:
            first=harness.submit()['run_id']
            assert sessions.entered.wait(5)
            second=harness.submit()['run_id']
            harness.client.execute({'action':'cancel','run_id':second,'request_id':'cancel-queued'})
            sessions.release.set()
            harness.wait(lambda:harness.status(second)['status']=='cancelled')
            harness.wait(lambda:harness.status(first)['status']=='completed')
            assert len(sessions.ports[0].executions)==2
        finally:
            harness.stop()

    def test_invalid_and_unsupported_source_never_enters_queue(self,tmp_path):
        harness=ResidentHarness(tmp_path).start()
        try:
            source=tmp_path/'bad.culs'
            source.write_text('let target = tube(); target << [missing:50uL];')
            with pytest.raises(ValueError,match='PROGRAM_DIAGNOSTICS_REJECTED'):
                harness.submit(source=str(source))
            source.write_text('let x = tube(); let d = phy(sample=x, quantity=temperature);')
            with pytest.raises(ValueError,match='HOST_PLAN_UNSUPPORTED'):
                harness.submit(source=str(source))
            assert harness.client.execute({'action':'runs'})['runs']==[]
            assert not harness.sessions.ports[0].executions
        finally:
            harness.stop()

    def test_configuration_change_rejected_on_restart(self,tmp_path):
        config=tmp_path/'config.json'
        config.write_text('{}')
        first=ResidentHarness(tmp_path,config=config).start()
        first.stop()
        config.write_text('{"changed":true}')
        second=ResidentHarness(tmp_path,config=config)
        second.thread.start()
        second.thread.join(5)
        assert not second.thread.is_alive()
        assert any('HOST_CONFIGURATION_MISMATCH' in str(error) for error in second.errors)
        assert not second.sessions.ports
        second.endpoint.with_name(second.endpoint.name+'.host.lock').unlink(missing_ok=True)

    def test_transport_shape_validation(self):
        for payload in (None,{'action':1},{'action':'submit','source':12},{'action':'runs','unexpected':True}):
            with pytest.raises(ValueError,match='HOST_REQUEST_INVALID'):
                ResidentProtocolAdapter.request(payload)

    @pytest.mark.parametrize("profile", ["transfer", "processing/thermal-hold", "processing/orbital-shake", "processing/magnetic-flowthrough", "processing/thermocycler", "processing/incubation", "heater-shaker-docking"])
    def test_official_simulator_resident_cli(self,tmp_path,profile):
        pytest.importorskip('culsma_opentrons')
        endpoint=Path('/private/tmp')/('culsma-cli-'+uuid4().hex[:12]+'.sock')
        database=tmp_path/'resident.sqlite3'
        process=subprocess.Popen([sys.executable,'-m','culsma_os.cli','serve','--socket',str(endpoint),
            '--host-db',str(database),'--driver-config',str(ROOT/'examples'/profile/'deck.json'),
            '--artifacts-dir',str(tmp_path/'artifacts')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        client=ResidentClientAdapter(endpoint,3)
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    pytest.fail(str(process.communicate()))
                try:
                    state=client.execute({'action':'host-status'})
                    if state['status']=='failed':
                        pytest.fail(str(state))
                    if state['status']=='ready':
                        break
                except OSError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail('official host startup timed out')
            source=ROOT/'examples'/profile/('transfer.culs' if profile=='transfer' else 'protocol.culs')
            submit=subprocess.run([sys.executable,'-m','culsma_os.cli','submit',str(source),
                '--socket',str(endpoint)],capture_output=True,text=True,timeout=15)
            assert submit.returncode==0,submit.stderr
            run_id=json.loads(submit.stdout)['run_id']
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                result=client.execute({'action':'status','run_id':run_id})
                if result['status']=='completed':
                    break
                assert result['status'] not in {'needs_reconciliation','failed'},result
                time.sleep(0.02)
            assert result['status']=='completed',result
            # The same resident device session must admit another complete protocol.
            second=client.execute({'action':'submit','source':str(source)})['run_id']
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                result=client.execute({'action':'status','run_id':second})
                if result['status']=='completed':
                    break
                assert result['status'] not in {'needs_reconciliation','failed'},result
                time.sleep(0.02)
            assert result['status']=='completed',result
            assert process.poll() is None
            with sqlite3.connect(database) as conn:
                assert conn.execute('SELECT count(*) FROM os_attempts').fetchone()[0]>=4
                assert conn.execute('SELECT count(*) FROM os_run_queue').fetchone()[0]==2
            process.terminate()
            process.communicate(timeout=10)
            assert process.returncode==0
            assert not endpoint.exists()
        finally:
            if process.poll() is None:
                try:
                    client.execute({'action':'shutdown'})
                    process.communicate(timeout=15)
                except BaseException:
                    process.kill()
                    process.communicate()
            endpoint.unlink(missing_ok=True)
            Path(str(endpoint)+'.host.lock').unlink(missing_ok=True)

    def test_new_boundaries_and_thread_local_composition(self):
        src=ROOT/'src/culsma_os'
        adapter=ast.parse((src/'program_manager/adapters/resident.py').read_text())
        for node in ast.walk(adapter):
            if isinstance(node,ast.ImportFrom):
                assert not any('Repository' in item.name or item.name=='CallerContext' for item in node.names)
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                assert node.func.attr not in {'advance_run','take_over_run','open_session','compile','acquire'}
        worker=(src/'program_manager/interactors/resident.py').read_text()
        assert 'sqlite3' not in worker and 'Sqlite' not in worker
        assert 'self.worker_factory.build' in (src/'lifecycle_manager/interactors.py').read_text()

