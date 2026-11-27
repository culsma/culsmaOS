import pytest

pytest.importorskip('mcp.server.mcpserver')
from starlette.testclient import TestClient

from culsma_os.console.models import ConsoleSettings
from culsma_os.remote_access.adapters.console_http import RemoteConsoleHTTP
from culsma_os.remote_access.adapters.identity import FileRemoteIdentityAdapter


def test_remote_console_requires_automation_grant_for_normal_mcp_tools(tmp_path):
    station = 'lab'
    grants = tmp_path / 'grants'
    projects = tmp_path / 'projects'
    projects.mkdir()
    settings = ConsoleSettings(tmp_path / 'station.endpoint',
                               drafts_path=tmp_path / 'drafts.sqlite3',
                               program_root=projects, home_path=tmp_path)
    read_token = tmp_path / 'read-token'
    token = tmp_path / 'automation-token'
    FileRemoteIdentityAdapter(grants, station).issue('reader', 1, read_token)
    grant = FileRemoteIdentityAdapter(grants, station, scope='automation').issue('operator', 1, token)

    with TestClient(RemoteConsoleHTTP(settings, station, grants),
                    base_url='http://127.0.0.1:18768') as client:
        def post(method, params=None, token_file=None):
            headers = {'Accept': 'application/json, text/event-stream'}
            if token_file is not None:
                headers['Authorization'] = 'Bearer ' + token_file.read_text().strip()
            return client.post('/mcp', headers=headers,
                               json={'jsonrpc': '2.0', 'id': 1, 'method': method,
                                     'params': params or {}})

        assert post('tools/list').status_code == 401
        assert post('tools/list', token_file=read_token).status_code == 401
        tools = post('tools/list', token_file=token).json()['result']['tools']
        names = {tool['name'] for tool in tools}
        assert {'station_status', 'create_document', 'start_program', 'control_run'} <= names
        assert 'confirm_loading' in names
        create = {'name': 'create_document',
                  'arguments': {'path': 'probe.culs', 'content': '// remote MCP probe\n'}}
        response = post('tools/call', create, token)
        assert response.status_code == 200
        assert not response.json()['result'].get('isError')
        assert (projects / 'probe.culs').read_text() == '// remote MCP probe\n'
        grant.unlink()
        assert post('tools/call', create, token).status_code == 401
