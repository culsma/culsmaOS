"""Scaffold boundary checks; no network, resident or hardware is started."""
import pytest
from culsma_os.auth.models import CallerContext, ConsoleAccessError
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.remote_access.adapters.client import RemoteStationClient
from culsma_os.remote_access.adapters.http import RemoteReadRequestAdapter
from culsma_os.remote_access.interactors import RemoteReadInteractor
from culsma_os.remote_access.models import RemoteAccessSettings


class VerifiedIdentity:
    def __init__(self, capabilities):
        self.capabilities = capabilities

    def execute(self, raw):
        if raw != 'Bearer test-only':
            raise ConsoleAccessError('TEST_UNAUTHENTICATED')
        return CallerContext('test-user', frozenset(self.capabilities))


class ReadOnlyResident:
    def __init__(self):
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        assert request == {'action': 'runs'}
        return {'runs': []}


def build(enabled=True, capabilities=('station:read', 'station:lab-1:read')):
    resident = ReadOnlyResident()
    reads = RemoteReadInteractor(RemoteAccessSettings('lab-1', enabled),
        VerifiedIdentity(capabilities), ConsoleCommandInteractor(resident))
    return RemoteReadRequestAdapter(reads), resident


@pytest.mark.parametrize('enabled,capabilities,credential,station', [
    (False, ('station:read', 'station:lab-1:read'), 'Bearer test-only', 'lab-1'),
    (True, ('station:read', 'station:lab-1:read'), 'wrong', 'lab-1'),
    (True, ('station:lab-1:read',), 'Bearer test-only', 'lab-1'),
    (True, ('station:read',), 'Bearer test-only', 'lab-1'),
    (True, ('station:read', 'station:lab-1:read'), 'Bearer test-only', 'lab-2'),
])
def test_denied_request_never_reaches_resident(enabled, capabilities, credential, station):
    adapter, resident = build(enabled, capabilities)
    with pytest.raises(ConsoleAccessError):
        adapter.handle(credential, {'station_id': station, 'operation': 'runs'})
    assert resident.calls == []


def test_remote_and_local_reads_share_the_console_use_case():
    adapter, resident = build()
    remote = adapter.handle('Bearer test-only', {'station_id': 'lab-1', 'operation': 'runs'})
    assert remote['data'] == {'runs': []}
    assert resident.calls == [{'action': 'runs'}]


@pytest.mark.parametrize('extra', [{'operation': 'initialize'}, {'action': 'start'},
    {'caller': 'admin'}, {'capabilities': ['setup:confirm']}, {'run_id': '../secret'}])
def test_scaffold_cannot_forward_execution_or_forged_identity(extra):
    adapter, resident = build()
    with pytest.raises(ValueError):
        adapter.handle('Bearer test-only', {'station_id': 'lab-1', 'operation': 'runs', **extra})
    assert resident.calls == []


def test_client_connection_failure_does_not_resubmit_or_fallback():
    class DisconnectedTransport:
        calls = 0
        def read(self, request):
            self.calls += 1
            raise OSError('disconnected')
    transport = DisconnectedTransport()
    with pytest.raises(OSError):
        RemoteStationClient('lab-1', transport).station_status()
    assert transport.calls == 1
