"""Exercise real MCP stdio and the HTTP gateway against a resident test station."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from threading import Thread
from unittest.mock import Mock

import pytest

pytest.importorskip('mcp.server.mcpserver')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from culsma_os.cli import CulsmaOSCLI
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import ConsoleReadError
from culsma_os.remote_access.adapters.transport import RemoteHTTPTransport
from culsma_os.remote_access.models import RemoteReadOperation, RemoteReadRequest
from culsma_os.remote_access.providers import RemoteAccessFactory
from tests.support.integration.resident_host import ResidentHarness


def test_remote_mcp_cli_reads_live_resident_and_enforces_grant(tmp_path, capsys):
    station = 'test-station'
    token_file = tmp_path / 'token'
    grants = tmp_path / 'grants'
    CulsmaOSCLI.main(['remote-grant', '--station-id', station, '--grants', str(grants),
                      '--subject', 'test-operator', '--token-file', str(token_file)])
    grant_path = Path(capsys.readouterr().out.strip())
    grant = json.loads(grant_path.read_text())
    assert token_file.read_text().strip() not in grant_path.read_text()

    resident = ResidentHarness(tmp_path).start()
    try:
        run_id = resident.submit()['run_id']
        resident.wait(lambda: resident.status(run_id)['status'] == 'completed')
        factory = RemoteAccessFactory()
        with factory.build_read_server(station, grants, resident.endpoint, 0) as gateway:
            thread = Thread(target=gateway.serve_forever)
            thread.start()
            url = f'http://127.0.0.1:{gateway.server_port}'
            try:
                asyncio.run(check_mcp(url, station, token_file, run_id, grant_path, grant))
            finally:
                gateway.shutdown()
                thread.join()
        transport = factory.build_transport(url, token_file)
        with pytest.raises(OSError, match='REMOTE_CONNECTION_UNAVAILABLE'):
            transport.read(RemoteReadRequest(station, RemoteReadOperation.RUNS))
        assert len(resident.client.execute({'action': 'runs'})['runs']) == 1
    finally:
        resident.stop()


async def check_mcp(url, station, token_file, run_id, grant_path, grant):
    command = StdioServerParameters(command=sys.executable, args=[
        '-m', 'culsma_os.cli', 'remote-mcp', '--connection', 'tunnel', '--url', url,
        '--station-id', station, '--token-file', str(token_file),
    ], env={'PYTHONPATH': os.pathsep.join(sys.path)})
    async with stdio_client(command) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            assert {tool.name for tool in (await client.list_tools()).tools} == {
                'station_status', 'list_runs', 'run_status',
            }
            status = await client.call_tool('station_status', {})
            assert status.structured_content['data']['host']['status'] == 'ready'
            runs = await client.call_tool('list_runs', {})
            assert runs.structured_content['data']['runs'][0]['run_id'] == run_id
            run = await client.call_tool('run_status', {'run_id': run_id})
            assert run.structured_content['data']['status'] == 'completed'

            grant_path.write_text(json.dumps({**grant, 'station_id': 'other'}))
            assert (await client.call_tool('list_runs', {})).is_error
            grant_path.write_text(json.dumps({**grant, 'expires_at': datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()}))
            assert (await client.call_tool('list_runs', {})).is_error
            grant_path.write_text(json.dumps(grant))
            assert not (await client.call_tool('list_runs', {})).is_error
            grant_path.unlink()
            assert (await client.call_tool('list_runs', {})).is_error


def test_transport_refuses_unencrypted_non_loopback_origin(tmp_path):
    with pytest.raises(ValueError, match='REMOTE_ENDPOINT_INVALID'):
        RemoteHTTPTransport('http://station.example', tmp_path / 'token')


def test_connection_selection_rejects_conflicting_settings(tmp_path):
    factory = RemoteAccessFactory()
    token = tmp_path / 'token'
    access = tmp_path / 'access.json'
    with pytest.raises(ValueError, match='tunnel requires a loopback HTTP URL'):
        factory.build_transport('https://station.example', token, mode='tunnel')
    with pytest.raises(ValueError, match='https requires an HTTPS URL'):
        factory.build_transport('http://127.0.0.1', token, mode='https')
    with pytest.raises(ValueError, match='cloudflare requires --access-token-file'):
        factory.build_transport('https://station.example', token, mode='cloudflare')
    with pytest.raises(ValueError, match='--access-token-file requires the cloudflare connection'):
        factory.build_transport('https://station.example', token, mode='https',
                                access_token_file=access)


def test_switching_https_gateway_changes_only_its_credentials(tmp_path, monkeypatch):
    factory = RemoteAccessFactory()
    token = tmp_path / 'token'
    token.write_text('a' * 43)
    access = tmp_path / 'access.json'
    access.write_text(json.dumps({'client_id': 'test.access', 'client_secret': 'test-secret'}))
    with pytest.raises(ValueError, match='REMOTE_ACCESS_REQUIRES_HTTPS'):
        factory.build_transport('http://127.0.0.1', token, mode='cloudflare',
                                access_token_file=access)

    response = Mock(status=302)
    connection = Mock()
    connection.getresponse.return_value.__enter__ = Mock(return_value=response)
    connection.getresponse.return_value.__exit__ = Mock(return_value=False)
    connect = Mock(return_value=connection)
    monkeypatch.setattr('culsma_os.remote_access.adapters.transport.HTTPSConnection', connect)
    transport = factory.build_transport('https://station.example', token, mode='cloudflare',
                                        access_token_file=access)
    request = RemoteReadRequest('test-station', RemoteReadOperation.STATION)
    with pytest.raises(ConsoleReadError, match='REMOTE_READ_FAILED'):
        transport.read(request)
    connect.assert_called_once_with('station.example', None, timeout=40)
    connection.request.assert_called_once()
    assert connection.request.call_args.args[0:2] == ('POST', '/v1/read')
    assert connection.request.call_args.args[3] == {
        'Authorization': 'Bearer ' + 'a' * 43,
        'Content-Type': 'application/json',
        'CF-Access-Client-Id': 'test.access',
        'CF-Access-Client-Secret': 'test-secret',
    }
    connection.close.assert_called_once()

    connection.reset_mock()
    transport = factory.build_transport('https://station.example', token, mode='https')
    with pytest.raises(ConsoleReadError, match='REMOTE_READ_FAILED'):
        transport.read(request)
    assert connection.request.call_args.args[3] == {
        'Authorization': 'Bearer ' + 'a' * 43,
        'Content-Type': 'application/json',
    }

    connect.reset_mock()
    # Existing Cloudflare configurations inferred the adapter from this file.
    transport = factory.build_transport('https://station.example', token, access_token_file=access)
    access.write_text(json.dumps({'client_id': 'test.access', 'client_secret': 'bad\r\nvalue'}))
    with pytest.raises(ConsoleAccessError, match='REMOTE_ACCESS_CREDENTIAL_INVALID'):
        transport.read(request)
    connect.assert_not_called()
