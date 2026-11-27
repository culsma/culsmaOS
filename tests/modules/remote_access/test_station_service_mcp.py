"""Remote MCP uses the same durable service admission as the local CLI."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip('mcp.server.mcpserver')
from starlette.testclient import TestClient
from culsma_os.console.models import ConsoleSettings
from culsma_os.lifecycle_manager.station_service import StationServiceInteractor, StationServiceRepository
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from culsma_os.remote_access.adapters.console_http import RemoteConsoleHTTP
from culsma_os.remote_access.adapters.identity import FileRemoteIdentityAdapter


@pytest.mark.parametrize('lost_response', [False, True])
@pytest.mark.parametrize('native_mode', [None, 'simulation', 'physical'])
def test_authenticated_initialization_reconciles_once(tmp_path, monkeypatch, lost_response, native_mode):
    port = Mock()
    port.describe.return_value = {'mode': 'physical', 'methods': [{'method_id': 'initialize', 'bundle_sha256': 'digest'}]}
    port.submit.return_value = {'state': 'accepted'}
    port.inspect.return_value = {'state': 'completed', 'scope': 'initialization_only'}
    service = StationServiceInteractor(StationServiceRepository(sqlite3.connect(
        tmp_path / 'services.db', check_same_thread=False)), port,
        SimpleNamespace(fingerprint='configuration-one'))
    enabled = [False]
    def permission(value=None):
        if value is not None:
            enabled[0] = value
        return {'available': True, 'enabled': enabled[0]}
    service.physical_permission = permission
    idle = Mock()
    lose = [lost_response]

    def execute(_self, payload):
        assert payload['action'] == 'station-service'
        request = payload['station_service_request']
        result = service.execute(request, idle)
        if request['action'] in ('initialize', 'execute-native') and lose[0]:
            lose[0] = False
            raise ConnectionError('response lost after admission')
        return result

    monkeypatch.setattr(ResidentClientAdapter, 'execute', execute)
    settings = ConsoleSettings(tmp_path / 'station.endpoint', drafts_path=tmp_path / 'drafts.db',
                               program_root=tmp_path / 'projects', home_path=tmp_path)
    identity = FileRemoteIdentityAdapter(tmp_path / 'grants', 'station', scope='automation')
    token = identity.pair('operator')
    with TestClient(RemoteConsoleHTTP(settings, 'station', identity.grants),
                    base_url='http://127.0.0.1:8768') as client:
        def rpc(method, params=None, authorized=True):
            headers = {'Accept': 'application/json, text/event-stream'}
            if authorized:
                headers['Authorization'] = 'Bearer ' + token
            return client.post('/mcp', headers=headers, json={
                'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})

        def call(name, arguments):
            if name == 'initialize_station' and native_mode:
                name = 'debug_execute_native_method'
                arguments = {**arguments, 'mode': native_mode, 'debug_reason': 'Investigate channel recovery'}
            return rpc('tools/call', {'name': name, 'arguments': arguments}).json()['result']

        tools = {t['name']: t for t in rpc('tools/list').json()['result']['tools']}
        assert not tools['initialize_station']['annotations']['readOnlyHint']
        assert tools['station_service_status']['annotations']['readOnlyHint']
        assert 'prepare_native_method' not in tools
        assert 'execute_native_method' not in tools
        assert not tools['debug_prepare_native_method']['annotations']['readOnlyHint']
        assert not tools['debug_execute_native_method']['annotations']['readOnlyHint']
        assert tools['native_method_logs']['annotations']['readOnlyHint']
        assert not tools['set_native_debug']['annotations']['readOnlyHint']
        assert call('describe_station_service', {})['structuredContent']['native_debug_enabled'] is False
        if native_mode:
            assert rpc('tools/call', {'name': 'set_native_debug', 'arguments': {'enabled': True}}, False).status_code == 401
            assert call('set_native_debug', {'enabled': True})['structuredContent']['native_debug_enabled']
            assert call('describe_station_service', {})['structuredContent']['native_debug_enabled']
            port.prepare_native.return_value = {'state': 'prepared', 'execution_started': False}
            staged = call('debug_prepare_native_method', {'entrypoint': 'test.hsl',
                'files': [{'path': 'test.hsl', 'data_base64': 'eA=='}], 'mode': native_mode, 'debug_reason': 'Investigate channel recovery'})
            assert staged['structuredContent']['execution_started'] is False
            port.submit.assert_not_called()
        assert call('describe_station_service', {})['structuredContent']['available']
        assert tools['physical_execution_status']['annotations']['readOnlyHint']
        assert not tools['set_physical_execution']['annotations']['readOnlyHint']
        assert rpc('tools/call', {'name': 'set_physical_execution', 'arguments': {'enabled': True}}, False).status_code == 401
        assert call('physical_execution_status', {})['structuredContent']['enabled'] is False
        assert call('set_physical_execution', {'enabled': True})['structuredContent']['enabled'] is True
        idle.side_effect = ValueError('HOST_CONFIGURATION_BUSY')
        assert call('set_physical_execution', {'enabled': False})['isError']
        assert call('physical_execution_status', {})['structuredContent']['enabled'] is True
        idle.side_effect = None
        assert call('set_physical_execution', {'enabled': False})['structuredContent']['enabled'] is False
        args = dict(request_id='init-one', method_id='initialize', bundle_sha256='digest', acknowledge_clearance=True)
        assert rpc('tools/call', {'name': 'initialize_station', 'arguments': args}, False).status_code == 401
        if native_mode != 'simulation':
            assert call('initialize_station', {**args, 'acknowledge_clearance': False})['isError']
        port.submit.assert_not_called()
        initial = call('initialize_station', args)
        if lost_response:
            assert initial['isError']
            assert 'STATION_SERVICE_CONNECTION_LOST' in initial['content'][0]['text']
        else:
            assert initial['structuredContent']['state'] == 'accepted'
        assert call('station_service_status', {'request_id': 'init-one'})['structuredContent']['state'] == 'completed'
        assert call('initialize_station', args)['structuredContent']['state'] == 'completed'
        assert call('initialize_station', {**args, 'method_id': 'different'})['isError']
        assert port.submit.call_count == 1
        assert port.inspect.call_count == 1
        assert not tools['cancel_station_service']['annotations']['readOnlyHint']
        cancel_args = {'request_id': 'cancel-me'}
        assert rpc('tools/call', {'name': 'cancel_station_service', 'arguments': cancel_args}, False).status_code == 401
        assert call('initialize_station', {**args, **cancel_args})['structuredContent']['state'] == 'accepted'
        port.cancel.return_value = {'state': 'cancelled', 'diagnostic': 'OPERATOR_CANCELLED'}
        assert call('cancel_station_service', cancel_args)['structuredContent']['state'] == 'cancelled'
        assert call('station_service_status', cancel_args)['structuredContent']['state'] == 'cancelled'
        assert call('cancel_station_service', cancel_args)['structuredContent']['state'] == 'cancelled'
        port.cancel.assert_called_once()
        service.require_settled()
        assert tools['run_logs']['annotations']['readOnlyHint']
        service.run_evidence = Mock(return_value={'attempts': [{'attempt_id':'attempt', 'mode':'physical',
            'context': {'description': {'entrypoint':'batch.hsl'}}}]})
        port.operation_logs.return_value = {'encoding':'base64','content':'eA==','offset':0,'next_offset':1}
        log_args = {'run_id':'run','attempt_id':'attempt','stream':'trace'}
        assert rpc('tools/call', {'name':'run_logs','arguments':log_args}, False).status_code == 401
        log = call('run_logs', log_args)['structuredContent']
        assert log['content'] == 'eA==' and log['run_id'] == 'run'
        assert call('run_logs', {**log_args,'attempt_id':'foreign'})['isError']
        assert port.operation_logs.call_count == 1
        if native_mode:
            assert call('set_native_debug', {'enabled': False})['structuredContent']['native_debug_enabled'] is False
            assert call('debug_prepare_native_method', {'entrypoint': 'test.hsl', 'files': [],
                'mode': native_mode, 'debug_reason': 'Inspect after closing'})['isError']
            assert port.prepare_native.call_count == 1
        identity.unpair(identity.pairings()[0]['id'])
        assert rpc('tools/call', {'name': 'initialize_station', 'arguments': args}).status_code == 401
