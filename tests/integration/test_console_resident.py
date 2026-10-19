import sqlite3

from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness
from tests.support.integration.resident_host import ResidentHarness, GateSessionFactory


class TestConsoleResident:
    def test_console_observes_the_same_run_without_another_session(self, tmp_path):
        resident = ResidentHarness(tmp_path).start()
        try:
            run_id = resident.submit()['run_id']
            resident.wait(lambda: resident.status(run_id)['status'] == 'completed')
            session_count = len(resident.sessions.ports)
            executions = [len(port.executions) for port in resident.sessions.ports]
            server = ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint, 0))
            with ConsoleHTTPHarness(server) as console:
                for _ in range(3):
                    code, _, station = console.request('GET', '/api/v1/station')
                    assert code == 200 and station['data']['devices']['hardware_observed'] is False
                    assert station['data']['runs'][0]['run_id'] == run_id
                code, _, detail = console.request('GET', '/api/v1/runs/'+run_id)
                assert code == 200 and detail['data']['status'] == 'completed'
                assert detail['data']['result']['os']['registered_material']['version'] > 0
                evidence = detail['data']['execution_evidence']
                assert evidence['hardware_observed'] is False and evidence['attempts']
                assert all(item['evidence']['outcome'] == 'completed' for item in evidence['attempts'])
                assert any(item['registration']['status'] == 'registered' for item in evidence['attempts'])
                assert 'execution_evidence' not in resident.status(run_id)
            assert len(resident.sessions.ports) == session_count
            assert [len(port.executions) for port in resident.sessions.ports] == executions
            with sqlite3.connect(resident.context.database_path) as connection:
                assert connection.execute('SELECT count(*) FROM os_run_queue').fetchone()[0] == 1
                assert connection.execute('SELECT count(*) FROM os_run_commands').fetchone()[0] == 0
        finally:
            resident.stop()

    def test_inspection_preserves_unknown_head_and_successor(self, tmp_path):
        sessions = GateSessionFactory(unknown=True); sessions.release.set()
        resident = ResidentHarness(tmp_path, sessions).start()
        try:
            first, second = resident.submit()['run_id'], resident.submit()['run_id']
            resident.wait(lambda: resident.status(first)['status'] == 'needs_reconciliation')
            count = len(sessions.ports[0].executions)
            server = ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint, 0))
            with ConsoleHTTPHarness(server) as console:
                code, _, station = console.request('GET', '/api/v1/station')
                assert code == 200 and station['data']['host']['blocked_run'] == first
                device = station['data']['devices']['devices'][0]
                assert device['unresolved_operations']
                code, _, detail = console.request('GET', '/api/v1/runs/'+first)
                assert code == 200 and detail['data']['status'] == 'needs_reconciliation'
                evidence = detail['data']['execution_evidence']['attempts']
                assert any(item['evidence']['outcome'] == 'unknown' for item in evidence)
                assert all(item['registration']['status'] != 'registered' for item in evidence)
                assert console.request('POST', '/api/v1/runs/'+first)[0] == 405
            assert resident.status(second)['status'] == 'ready'
            assert len(sessions.ports[0].executions) == count
        finally:
            resident.stop()


    def test_complete_pcr_evidence_survives_console_reconnect(self, tmp_path):
        from tests.support.console.http import ConsoleProtocolHarness
        from tests.support.paths import ROOT
        with ConsoleProtocolHarness(tmp_path,'pcr-benchmark') as resident:
            run_id = resident.client.execute({'action':'submit',
                'source':str(ROOT/'examples/pcr-benchmark/protocol.culs')})['run_id']
            resident.wait(lambda: resident.client.execute({'action':'runs'})['runs'][0]['status'] == 'completed', timeout=90)
            views = []
            with sqlite3.connect(resident.database) as connection:
                counts = [connection.execute('SELECT count(*) FROM '+table).fetchone()[0]
                          for table in ['os_attempts','os_evidence','os_material_changes']]
            for _ in range(2):
                server = ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint, 0))
                with ConsoleHTTPHarness(server) as console:
                    code, _, detail = console.request('GET','/api/v1/runs/'+run_id)
                    assert code == 200
                    view = detail['data']['execution_evidence']
                    assert view['accounting'] == 'recorded' and len(view['attempts']) == counts[0]
                    assert len(view['attempts']) >= 90
                    assert all(row['evidence']['outcome'] == 'completed' for row in view['attempts'])
                    assert sum(row['registration']['status'] == 'registered' for row in view['attempts']) == counts[2]
                    views.append(view)
            assert views[0] == views[1]
            with sqlite3.connect(resident.database) as connection:
                assert counts == [connection.execute('SELECT count(*) FROM '+table).fetchone()[0]
                                  for table in ['os_attempts','os_evidence','os_material_changes']]


    def test_same_console_recovers_when_selected_service_starts(self, tmp_path):
        resident = ResidentHarness(tmp_path)
        server = ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint, 0))
        with ConsoleHTTPHarness(server) as console:
            assert console.request('GET','/api/v1/station')[0] == 503
            assert not resident.context.database_path.exists()
            resident.start()
            try:
                code, _, station = console.request('GET','/api/v1/station')
                assert code == 200 and station['data']['host']['status'] == 'ready'
                assert station['data']['runs'] == []
            finally:
                resident.stop()
            assert console.request('GET','/api/v1/station')[0] == 503
