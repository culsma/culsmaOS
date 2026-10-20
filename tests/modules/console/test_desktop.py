import json
import sys
import threading
from types import SimpleNamespace

import pytest
from culsma_os.console.interactors import DesktopConsoleInteractor
from culsma_os.console.adapters.desktop import NativeConsoleProcessAdapter
from culsma_os.program_manager.models import ConsoleReadError


class DesktopFixture:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.events = []
        self.stop = threading.Event()
        self.commands = self
        self.url = 'http://127.0.0.1:1234'
        self.sessions = SimpleNamespace(execute=lambda: {'access_token': 'private-test-capability'})

    def execute(self, request):
        value = next(self.statuses)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(data={'host': {'status': value}})

    def start(self):
        self.events.append('start-resident')

    def serve_forever(self):
        self.events.append('serve')
        self.stop.wait(5)

    def run(self, value):
        self.connection = value
        self.events.append('run-ui')
        return 0

    def shutdown(self):
        self.events.append('stop-console')
        self.stop.set()

    def server_close(self):
        self.events.append('close-console')


def test_desktop_waits_for_ready_and_passes_private_connection():
    f = DesktopFixture([ConsoleReadError('CONSOLE_HOST_UNAVAILABLE','unavailable'), 'starting', 'ready'])
    assert DesktopConsoleInteractor(f, f.sessions, f, f).execute() == 0
    assert f.events.index('start-resident') < f.events.index('run-ui')
    assert f.connection == {'schema':'culsma_desktop_v1','origin':f.url,'access_token':'private-test-capability'}
    assert f.events[-2:] == ['stop-console','close-console']
    assert f.events.count('start-resident') == 1  # Closing UI never requests station shutdown.


def test_attach_does_not_start_another_resident():
    f = DesktopFixture(['ready'])
    DesktopConsoleInteractor(f, f.sessions, f).execute()
    assert 'start-resident' not in f.events


@pytest.mark.parametrize('state,diagnostic', [('failed','DESKTOP_STATION_NOT_READY'),('starting','DESKTOP_STARTUP_TIMEOUT')])
def test_desktop_failed_or_timed_out_start_never_opens_ui(state, diagnostic):
    f = DesktopFixture([state])
    with pytest.raises(ValueError, match=diagnostic):
        DesktopConsoleInteractor(f, f.sessions, f, timeout=0).execute()
    assert f.events == ['close-console']


def test_attach_missing_resident_is_explicit():
    f = DesktopFixture([ConsoleReadError('CONSOLE_HOST_UNAVAILABLE','unavailable')])
    with pytest.raises(ValueError, match='DESKTOP_RESIDENT_REQUIRED'):
        DesktopConsoleInteractor(f, f.sessions, f).execute()
    assert f.events == ['close-console']


def test_native_process_sends_credential_on_pipe_only(tmp_path):
    # Child records argv and stdin to prove credentials never enter the command line.
    child = tmp_path/'child'
    result = tmp_path/'result.json'
    child.write_text(f'#!{sys.executable}\nimport sys,json\nfrom pathlib import Path\nPath({str(result)!r}).write_text(json.dumps([sys.argv,json.loads(sys.stdin.readline())]))\n')
    child.chmod(0o700)
    assert NativeConsoleProcessAdapter(child).run({'access_token':'private-test-value'}) == 0
    args, connection = json.loads(result.read_text())
    assert args == [str(child)] and connection['access_token'] == 'private-test-value'


def test_resident_process_uses_selected_state_root_without_global_environment_change(tmp_path, monkeypatch):
    import os
    from culsma_os.console.adapters.desktop import ResidentProcessAdapter
    calls = []
    monkeypatch.setattr('culsma_os.console.adapters.desktop.subprocess.Popen', lambda *a, **kw: calls.append((a, kw)))
    before = os.environ.get('CULSMA_OS_STATION_ROOT')
    port = ResidentProcessAdapter(['python','-m','culsma_os.cli','serve'],tmp_path/'logs/resident.log',tmp_path/'stations')
    port.start()
    args, values = calls[0]
    assert args[0] == ('python','-m','culsma_os.cli','serve')
    assert values['env']['CULSMA_OS_STATION_ROOT'] == str(tmp_path/'stations')
    assert values['start_new_session'] is True
    assert os.environ.get('CULSMA_OS_STATION_ROOT') == before
    assert (tmp_path/'logs/resident.log').is_file()


def test_desktop_cli_missing_application_has_no_startup_side_effect(tmp_path, capsys):
    from culsma_os.cli import CulsmaOSCLI
    with pytest.raises(SystemExit) as error:
        CulsmaOSCLI.main(['desktop','--state-dir',str(tmp_path/'state'),'--application',str(tmp_path/'missing')])
    assert error.value.code == 2
    assert 'DESKTOP_APPLICATION_NOT_INSTALLED' in capsys.readouterr().err
    assert not (tmp_path/'state').exists()
