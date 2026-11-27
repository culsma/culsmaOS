"""Exercise native maintenance through OS and the direct driver with a fake VENUS API."""
import base64
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from culsma_os.lifecycle_manager.station_service import StationServiceInteractor, StationServiceRepository


class NativeTestVenus:
    def __init__(self, traces, mode, failure):
        self.traces, self.mode, self.failure = traces, mode, failure
        self.state, self.starts, self.path = 0, 0, None

    def exchange(self, port, verb, endpoint, body=None):
        if endpoint == 'run-state':
            return self.state
        if endpoint == 'load':
            assert body['Simulation'] is (self.mode == 'simulation')
            self.path, self.state = body['FilePath'], 1
        if endpoint == 'start':
            self.starts += 1
            self.state = 0
            body_marker = '[CULSMA] BODY_ERROR test_fault' if self.failure else '[CULSMA] BODY_RETURNED;'
            text = (f'SYSTEM : Execute method - start; Method file {self.path}\n'
                    f'USER : Trace {body_marker}\n'
                    'SYSTEM : Execute method - complete;\nSYSTEM : End method - complete;\n')
            self.traces.mkdir(exist_ok=True)
            (self.traces / 'maintenance_test.trc').write_text(text)
        return {'result': True}


@pytest.mark.parametrize('mode', ['simulation', 'physical'])
@pytest.mark.parametrize('failure', [False, True])
def test_bundle_execute_trace_and_cancel(tmp_path, mode, failure):
    from culsma_driver_hamilton.interactors.native_maintenance_interactor import HamiltonNativeMaintenanceInteractor
    from culsma_driver_hamilton.venus.station import VenusStation, VenusStationClient
    from culsma_hamilton_os.providers import HamiltonVenusTransferInteractor

    traces = tmp_path / 'traces'
    vendor = NativeTestVenus(traces, mode, failure)
    station = VenusStation(tmp_path / 'venus', {
        'schema': 'culsma_hamilton_venus_v1', 'methods': [],
        'allow_physical_execution': True, 'allow_venus_simulation': True,
        'venus': {'port': 1, 'trace_directory': str(traces)},
    }, vendor)
    client = VenusStationClient(station, mode)
    backend = HamiltonVenusTransferInteractor(client, generated_methods=station.generated_methods)
    port = HamiltonNativeMaintenanceInteractor(backend)
    db = tmp_path / 'os.db'
    configuration = SimpleNamespace(fingerprint='config')
    service = StationServiceInteractor(StationServiceRepository(sqlite3.connect(db)), port, configuration, native_debug_enabled=True)
    idle = lambda: None
    bundle = service.execute({'action': 'prepare-native', 'debug_reason': 'Investigate channel recovery', 'mode': mode, 'entrypoint': 'maintenance.hsl',
        'files': [{'path': 'maintenance.hsl', 'data_base64': base64.b64encode(b'// test only').decode()}]}, idle)
    request = {'action': 'execute-native', 'debug_reason': 'Investigate channel recovery', 'request_id': 'native-one', 'mode': mode,
        'method_id': bundle['method_id'], 'bundle_sha256': bundle['bundle_sha256'], 'acknowledge_clearance': True}
    assert service.execute(request, idle)['state'] == 'accepted'
    client.wait(port.request(request['request_id'], bundle), timeout=5, interval=.01)
    result = service.execute({'action': 'status', 'request_id': 'native-one'}, idle)
    assert result['state'] == ('unknown' if failure else 'completed')
    assert result['material_registration'] is False
    if failure:
        assert result['receipt']['stop_observed'] is True
        with pytest.raises(ValueError, match='UNRESOLVED'):
            service.require_settled()
        result = service.execute({'action': 'cancel', 'request_id': 'native-one'}, idle)
        assert result['state'] == 'cancelled'
    service.require_settled()
    page = service.execute({'action': 'native-logs', 'request_id': 'native-one', 'stream': 'trace'}, idle)
    assert b'Execute method - start' in base64.b64decode(page['content'])
    assert vendor.starts == 1
    restored = StationServiceInteractor(StationServiceRepository(sqlite3.connect(db)), port, configuration, native_debug_enabled=True)
    assert restored.execute(request, idle) == result
    assert vendor.starts == 1
