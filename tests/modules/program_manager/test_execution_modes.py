from pathlib import Path
import json
import sqlite3
import sys
import pytest
from culsma import cli as language_cli
from culsma_os.bootstrap import OSApplicationFactory, HostLeaseFactory
from culsma_os.cli import CulsmaOSCLI
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from tests.support.common import FakeSessionFactory, FakeDevicePort, ProgramFixture
from tests.support.program_manager.execution_modes import InterruptedDevicePort, InterruptedSessionFactory


class TestExecutionModes:
    def test_repeated_one_shot_runs_close_each_host_without_a_queue(self, tmp_path):
        sessions = FakeSessionFactory()
        runner = OSApplicationFactory({'fake': sessions}).build_program_runner()
        database = tmp_path / 'one-shot.sqlite3'
        for _ in range(2):
            result = runner.execute_pipeline([ProgramFixture.source], driver_name='fake',
                host_database_path=database, driver_artifacts_dir=tmp_path / 'artifacts')
            assert result['output']['ok']
            assert result['result']['os']['status'] == 'completed'
            assert all(port.closed for port in sessions.ports)
        assert len(sessions.ports) == 2
        assert [len(port.executions) for port in sessions.ports] == [2, 2]
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT count(*) FROM os_runs WHERE status='completed'").fetchone()[0] == 2
            assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='os_run_queue'").fetchone()

    @pytest.mark.parametrize('entry', ['language', 'os'])
    def test_run_cli_stays_one_shot_without_resident_discovery(self, tmp_path, monkeypatch, capsys, entry):
        sessions = FakeSessionFactory()
        runner = OSApplicationFactory({'opentrons-simulator': sessions}).build_program_runner()
        monkeypatch.setattr(OSApplicationFactory, 'build_program_runner', lambda self: runner)
        def forbidden(*args, **kwargs):
            raise AssertionError('One-shot run must not discover, start or connect to a resident host')
        monkeypatch.setattr(OSApplicationFactory, 'build_resident_host', forbidden)
        monkeypatch.setattr(ResidentClientAdapter, 'execute', forbidden)
        monkeypatch.setenv('CULSMA_OS_SOCKET', str(tmp_path / 'unused.sock'))
        artifacts = tmp_path / 'artifacts'
        arguments = ['run', str(ProgramFixture.source), '--driver', 'opentrons-simulator',
                     '--artifacts-dir', str(artifacts)]
        if entry == 'language':
            monkeypatch.setattr(sys, 'argv', ['culsma', *arguments, '--json'])
            assert language_cli.main() is None
        else:
            with pytest.raises(SystemExit) as outcome:
                CulsmaOSCLI.main(arguments)
            assert outcome.value.code == 0
        if entry == 'language':
            assert json.loads(capsys.readouterr().out)['report']['os']['status'] == 'completed'
        assert len(sessions.ports) == 1
        assert sessions.ports[0].closed
        assert len(sessions.ports[0].executions) == 2
        assert json.loads((artifacts / 'run.json').read_text())['ok']
        assert not (tmp_path / 'unused.sock').exists()

    def test_interrupted_one_shot_closes_host_and_preserves_uncertain_intent(self, tmp_path):
        sessions = InterruptedSessionFactory()
        runner = OSApplicationFactory({'fake': sessions}).build_program_runner()
        database = tmp_path / 'one-shot.sqlite3'
        with pytest.raises(KeyboardInterrupt):
            runner.execute_pipeline([ProgramFixture.source], driver_name='fake', host_database_path=database)
        assert sessions.ports[0].closed
        with sqlite3.connect(database) as connection:
            assert connection.execute('SELECT count(*) FROM os_attempts').fetchone()[0] == 1
            assert connection.execute('SELECT count(*) FROM os_evidence').fetchone()[0] == 0
            assert connection.execute('SELECT status FROM os_runs').fetchone()[0] == 'waiting'
        context = HostBuildContext(database, 'fake', None, tmp_path / 'artifacts')
        lease = HostLeaseFactory().build(context)
        lease.acquire()
        lease.close()
        # Releasing the process lease is distinct from releasing the uncertain run.
        next_sessions = FakeSessionFactory()
        next_runner = OSApplicationFactory({'fake': next_sessions}).build_program_runner()
        result = next_runner.execute_pipeline([ProgramFixture.source], driver_name='fake', host_database_path=database)
        assert not result['output']['ok']
        assert not next_sessions.ports[0].executions
        assert next_sessions.ports[0].closed

