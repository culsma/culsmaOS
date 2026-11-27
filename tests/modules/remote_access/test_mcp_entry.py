"""Real MCP SDK dispatch through a fake wire/identity/resident, without sockets."""
import asyncio
from dataclasses import asdict

import pytest

pytest.importorskip('mcp.server.mcpserver')
from mcp.server.mcpserver.exceptions import ToolError
from culsma_os.auth.models import CallerContext, ConsoleAccessError
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.remote_access.adapters.http import RemoteReadRequestAdapter
from culsma_os.remote_access.interactors import RemoteReadInteractor
from culsma_os.remote_access.models import RemoteAccessSettings
from culsma_os.remote_access.providers import RemoteAccessFactory


class TestIdentity:
    __test__ = False

    def execute(self, credential):
        if credential != 'test-only':
            raise ConsoleAccessError('TEST_UNAUTHENTICATED')
        return CallerContext('test-user', frozenset({'station:read', 'station:lab-1:read'}))


class FakeResident:
    def __init__(self):
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return {
            'host-status': {'status': 'test-only'}, 'device-status': {},
            'runs': {'runs': []}, 'layout-status': {},
            'status': {'run_id': 'run-1', 'status': 'completed'},
            'run-evidence': {},
        }[request['action']]


class InMemoryWire:
    """Test-only substitute for the unimplemented authenticated HTTPS transport."""
    def __init__(self, receiver):
        self.receiver = receiver
        self.credential = 'test-only'
        self.calls = []

    def read(self, request):
        self.calls.append(request)
        return self.receiver.handle(self.credential, asdict(request))


def build():
    resident = FakeResident()
    receiver = RemoteReadRequestAdapter(RemoteReadInteractor(
        RemoteAccessSettings('lab-1', enabled=True), TestIdentity(),
        ConsoleCommandInteractor(resident)))
    wire = InMemoryWire(receiver)
    server = RemoteAccessFactory().build_mcp('lab-1', wire).make_server()
    return server, wire, resident


def test_mcp_registers_only_three_read_tools_without_identity_or_station_arguments():
    server, wire, resident = build()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {'station_status', 'list_runs', 'run_status'}
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert set(tool.input_schema['properties']) == ({'run_id'} if tool.name == 'run_status' else set())
    assert wire.calls == resident.calls == []


@pytest.mark.parametrize('tool,args,resource,actions', [
    ('station_status', {}, 'station', ['host-status', 'device-status', 'runs', 'layout-status']),
    ('list_runs', {}, 'runs', ['runs']),
    ('run_status', {'run_id': 'run-1'}, 'run', ['status', 'run-evidence']),
])
def test_sdk_tool_dispatch_reaches_existing_os_read_use_case(tool, args, resource, actions):
    server, wire, resident = build()
    result = asyncio.run(server.call_tool(tool, args))
    assert result.structured_content['resource'] == resource
    assert [call['action'] for call in resident.calls] == actions
    assert len(wire.calls) == 1 and wire.calls[0].station_id == 'lab-1'


def test_unknown_execution_tool_cannot_reach_transport():
    server, wire, resident = build()
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool('start_program', {}))
    assert wire.calls == resident.calls == []


def test_authentication_denial_propagates_through_mcp_without_resident_access():
    server, wire, resident = build()
    wire.credential = 'invalid'
    with pytest.raises(ToolError, match='TEST_UNAUTHENTICATED'):
        asyncio.run(server.call_tool('list_runs', {}))
    assert resident.calls == []


def test_connection_failure_is_sanitized_and_not_retried():
    class BrokenWire:
        calls = 0
        def read(self, request):
            self.calls += 1
            raise OSError('secret credential in vendor error')
    wire = BrokenWire()
    server = RemoteAccessFactory().build_mcp('lab-1', wire).make_server()
    with pytest.raises(ToolError, match='REMOTE_CONNECTION_UNAVAILABLE') as error:
        asyncio.run(server.call_tool('list_runs', {}))
    assert 'secret credential' not in str(error.value)
    assert wire.calls == 1


def test_invalid_run_id_is_rejected_before_transport():
    server, wire, resident = build()
    with pytest.raises(ToolError, match='REMOTE_READ_REQUEST_INVALID'):
        asyncio.run(server.call_tool('run_status', {'run_id': '../escape'}))
    assert wire.calls == resident.calls == []
