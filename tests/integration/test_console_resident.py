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
                assert console.request('POST', '/api/v1/runs/'+first)[0] == 405
            assert resident.status(second)['status'] == 'ready'
            assert len(sessions.ports[0].executions) == count
        finally:
            resident.stop()
