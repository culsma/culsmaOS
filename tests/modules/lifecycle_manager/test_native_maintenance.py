import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from culsma_os.lifecycle_manager.station_service import StationServiceInteractor, StationServiceRepository


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / 'services.db'
    port = Mock()
    port.submit.return_value = {'state': 'accepted'}
    port.inspect.return_value = {'state': 'completed'}
    service = StationServiceInteractor(StationServiceRepository(sqlite3.connect(path)), port,
                                      SimpleNamespace(fingerprint='configuration'), native_debug_enabled=True)
    request = {'action': 'execute-native', 'debug_reason': 'Investigate channel recovery', 'request_id': 'native-1', 'method_id': 'bundle',
               'bundle_sha256': 'hash', 'mode': 'simulation'}
    return path, service, port, request, Mock()


def test_prepare_stages_only_and_preserves_driver_contract(setup):
    _, service, port, _, idle = setup
    # A different driver's native format must pass through the OS unchanged.
    files = [{'path': 'service.py', 'data_base64': 'eA=='}]
    port.prepare_native.return_value = {'state': 'prepared', 'execution_started': False}
    assert service.execute({'action': 'prepare-native', 'debug_reason': 'Investigate channel recovery', 'entrypoint': 'service.py',
        'files': files, 'mode': 'simulation'}, idle)['execution_started'] is False
    port.prepare_native.assert_called_once_with('service.py', files, 'simulation')
    port.submit.assert_not_called()
    assert service.repository.unsettled() is None
    idle.assert_called_once()


def test_native_request_reconnects_without_replay_and_can_cancel(setup):
    path, service, port, request, idle = setup
    assert service.execute(request, idle)['state'] == 'accepted'
    with pytest.raises(ValueError, match='UNRESOLVED'):
        service.require_settled()
    restored = StationServiceInteractor(StationServiceRepository(sqlite3.connect(path)), port, service.configuration, native_debug_enabled=True)
    assert restored.execute(request, idle)['state'] == 'completed'
    assert restored.execute(request, idle)['state'] == 'completed'
    port.submit.assert_called_once()
    restored.require_settled()
    assert restored.execute({**request, 'request_id': 'native-2'}, idle)['state'] == 'accepted'
    port.cancel.return_value = {'state': 'cancelled'}
    assert restored.execute({'action': 'cancel', 'request_id': 'native-2'}, idle)['state'] == 'cancelled'
    restored.require_settled()


def test_physical_clearance_mode_and_cross_operation_identity(setup):
    _, service, port, request, idle = setup
    with pytest.raises(ValueError, match='CLEARANCE'):
        service.execute({**request, 'mode': 'physical'}, idle)
    with pytest.raises(ValueError, match='MODE_REQUIRED'):
        service.execute({**request, 'mode': 'auto'}, idle)
    port.submit.assert_not_called()
    service.execute({**request, 'mode': 'physical', 'acknowledge_clearance': True}, idle)
    for changed in ({'mode': 'simulation'}, {'action': 'initialize'}, {'bundle_sha256': 'different'}):
        with pytest.raises(ValueError, match='ID_CONFLICT'):
            service.execute({**request, **changed}, idle)


def test_log_paging_works_while_busy_and_after_completion(setup):
    _, service, port, request, idle = setup
    service.execute(request, idle)
    port.logs.return_value = {'encoding': 'base64', 'content': 'eA==', 'offset': 0, 'next_offset': 1}
    query = {'action': 'native-logs', 'request_id': 'native-1', 'stream': 'trace', 'limit': 1}
    assert service.execute(query, idle)['stream'] == 'trace'
    service.execute({'action': 'status', 'request_id': 'native-1'}, idle)
    assert service.execute(query, idle)['next_offset'] == 1
    assert idle.call_count == 1
    for changed in ({'offset': -1}, {'limit': 0}, {'stream': '../arbitrary'}):
        with pytest.raises(ValueError, match='CURSOR'):
            service.execute({**query, **changed}, idle)


def test_lost_dispatch_reply_keeps_original_request(setup):
    _, service, port, request, idle = setup
    port.submit.side_effect = ConnectionError()
    assert service.execute(request, idle)['state'] == 'unknown'
    port.inspect.return_value = {'state': 'running'}
    assert service.execute(request, idle)['state'] == 'running'
    port.submit.assert_called_once()


def test_native_debug_reason_is_required_and_survives_reconnect(setup):
    path, service, port, request, idle = setup
    for reason in (None, "", "  ", 12):
        with pytest.raises(ValueError, match="DEBUG_REASON_REQUIRED"):
            service.execute({**request, "debug_reason": reason}, idle)
    port.submit.assert_not_called()
    result = service.execute(request, idle)
    assert result["execution_origin"] == "native_debug"
    assert result["experiment_verified"] is False
    restored = StationServiceInteractor(StationServiceRepository(sqlite3.connect(path)), port, service.configuration, native_debug_enabled=True)
    result = restored.execute({"action": "status", "request_id": request["request_id"]}, idle)
    assert result["debug_reason"] == request["debug_reason"]
    assert result["experiment_verified"] is False
    with pytest.raises(ValueError, match="ID_CONFLICT"):
        restored.execute({**request, "debug_reason": "Changed task"}, idle)


def test_normal_resident_rejects_native_dispatch(setup):
    _, enabled, port, request, idle = setup
    resident = StationServiceInteractor(enabled.repository, port, enabled.configuration)
    for action in ('prepare-native', 'execute-native'):
        with pytest.raises(ValueError, match='STATION_NATIVE_DEBUG_DISABLED'):
            resident.execute({**request, 'action': action}, idle)
    port.prepare_native.assert_not_called()
    port.submit.assert_not_called()
    assert resident.repository.unsettled() is None
