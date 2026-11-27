"""CulsmaOS executes a Hamilton method via the in-process driver with a fake VENUS API."""
from dataclasses import replace
from pathlib import Path
import json

import pytest

from tests.support.integration.hamilton import fixture
from tests.support.integration.hamilton_setup import SetupFixture
from culsma_os.bootstrap import OSApplicationFactory


def test_new_venus_configuration_initializes_and_shutdown_waits(fixture, tmp_path, monkeypatch):
    import sqlite3
    from threading import Event, Thread
    from types import SimpleNamespace
    from unittest.mock import Mock
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
    from culsma_driver_hamilton.venus.adapters.venus import VenusLocalApiAdapter
    from culsma_os.lifecycle_manager.station_service import StationServiceInteractor, StationServiceRepository
    from culsma_os.program_manager.interactors.resident import ResidentCommandInteractor

    _, context = fixture
    config = json.loads(context.config_path.read_text())
    config.pop('agent')
    traces = tmp_path / 'traces'
    config.update(mode='physical', venus={'port': 1, 'trace_directory': str(traces)})
    context.config_path.write_text(json.dumps(config))
    context = replace(context, driver_name='hamilton-venus')
    started, release, closed = Event(), Event(), Event()

    class InitializationVendor(TestVenus):
        def exchange(self, port, verb, endpoint, body=None):
            if endpoint == 'start':
                started.set()
                assert release.wait(5)
            result = super().exchange(port, verb, endpoint, body)
            if endpoint == 'start':
                trace = traces / (Path(self.path).stem + '_test.trc')
                trace.write_text(trace.read_text().replace(
                    'ML_STAR : Aspirate (Single Step) - complete;\nML_STAR : Dispense (Single Step) - complete;',
                    'USER : Trace [CULSMA] INITIALIZE_REQUEST;\n'
                    'ML_STAR : Initialize (Single Step) - start;\n'
                    'ML_STAR : Initialize (Single Step) - complete;\n'
                    'USER : Trace [CULSMA] INITIALIZE_RETURNED;'))
            return result

    vendor = InitializationVendor(traces, None)
    monkeypatch.setattr(VenusLocalApiAdapter, 'exchange', lambda self, *args: vendor.exchange(*args))
    factory = HamiltonOSDeviceFactory()
    port = factory.build_station_service(context)
    factory.build_physical_permission(context)(True)
    connection = sqlite3.connect(tmp_path / 'services.sqlite3')
    service = StationServiceInteractor(StationServiceRepository(connection), port, SimpleNamespace(fingerprint='config'))
    method, = service.execute({'action': 'describe'}, lambda: None)['details']['methods']
    request = {'action': 'initialize', 'request_id': 'initialize-new',
               'method_id': method['method_id'], 'bundle_sha256': method['bundle_sha256'],
               'acknowledge_clearance': True}
    assert service.execute(request, lambda: None)['state'] == 'accepted'
    inspector = Mock()
    commands = SimpleNamespace(station_service=service, supplies=None, inspector=inspector)

    def close_commands():
        ResidentCommandInteractor.close(commands)
        closed.set()

    closing = Thread(target=close_commands)
    try:
        assert started.wait(5)
        closing.start()
        assert not closed.wait(.1)
        inspector.close.assert_not_called()
    finally:
        release.set()
        closing.join(5)
    assert closed.is_set()
    result = service.execute({'action': 'status', 'request_id': request['request_id']}, lambda: None)
    assert result['state'] == 'completed'
    assert result['receipt']['vendor_cleanup_completed'] is True
    assert result['receipt']['start_requests'] == 1
    assert result['receipt']['files']['initialize_layout.lay']
    inspector.close.assert_called_once()
    connection.close()


class TestVenus:
    __test__ = False

    def __init__(self, traces, fault):
        self.traces, self.fault = traces, fault
        self.calls, self.path, self.state = [], None, 0

    def exchange(self, port, verb, endpoint, body=None):
        self.calls.append((verb, endpoint, body))
        if endpoint == 'run-state':
            return self.state
        if endpoint == 'load':
            assert body['Simulation'] is False
            self.path = body['FilePath']
            self.state = 1
            if self.fault == 'lost-load':
                raise OSError('test: load response lost')
        if endpoint == 'start':
            self.state = 0
            text = f'''SYSTEM : Execute method - start; Method file {self.path}
ML_STAR : Aspirate (Single Step) - complete;
ML_STAR : Dispense (Single Step) - complete;
USER : Trace [CULSMA] BODY_RETURNED;
SYSTEM : Execute method - complete;
SYSTEM : End method - complete;'''
            if self.fault in ('monitor-pass', 'monitor-empty', 'monitor-missing'):
                contract = json.loads((Path(self.path).parent / 'pipetting-monitoring.json').read_text())
                lines = [f'SYSTEM : Execute method - start; Method file {self.path}']
                for action in contract['actions']:
                    prefix = 'USER : Trace - complete; [CULSMA_PIPETTING] '
                    lines.append(prefix + 'BEGIN ' + action['token'])
                    if self.fault == 'monitor-missing' and action['action'] == 'aspirate':
                        lines.append('USER : Trace - complete; [CULSMA] BODY_ERROR missing_step_return')
                        break
                    code = 102 if self.fault == 'monitor-empty' and action['action'] == 'aspirate' else 0
                    lines.append(prefix + 'RESULT ' + action['token'] + ' error=' + str(code))
                    if code:
                        lines.append('USER : Trace - complete; [CULSMA] BODY_ERROR pipetting_monitoring_failed')
                        break
                else:
                    lines.append('USER : Trace [CULSMA] BODY_RETURNED;')
                lines += ['SYSTEM : Execute method - complete;', 'SYSTEM : End method - complete;']
                text = '\n'.join(lines)
            if self.fault == 'missing-cleanup':
                text = text.replace('End method - complete;', 'End method - start;')
            self.traces.mkdir(exist_ok=True)
            (self.traces / (Path(self.path).stem + '_test.trc')).write_text(text)
            if self.fault == 'lost-start':
                raise OSError('test: start response lost after completion')
        return {'result': True}


@pytest.mark.parametrize('fault', [None, 'lost-start', 'lost-load', 'missing-cleanup', 'monitor-pass', 'monitor-empty', 'monitor-missing'])
def test_os_calls_venus_through_the_driver(fixture, tmp_path, monkeypatch, fault):
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
    from culsma_driver_hamilton.venus.adapters.venus import VenusLocalApiAdapter
    from culsma_driver_hamilton.venus.simulation.interactors import VenusPhysicalExecutionInteractor

    compiled, context = fixture
    config = json.loads(context.config_path.read_text())
    traces = tmp_path / 'traces'
    config.pop('agent')
    config.update(mode='physical', execution_strategy='batch',
                  venus={'port': 1, 'trace_directory': str(traces)})
    if fault and fault.startswith('monitor-'):
        config['execution']['pipetting']['monitoring'] = {
            'aspiration': 'mad_1000ul', 'liquid_level': 'capacitive', 'submerge_depth_mm': 2,
        }
    context.config_path.write_text(json.dumps(config))
    context = replace(context, driver_name='hamilton-venus')
    vendor = TestVenus(traces, fault)
    monkeypatch.setattr(VenusLocalApiAdapter, 'exchange',
                        lambda self, *args: vendor.exchange(*args))
    initialize = VenusPhysicalExecutionInteractor.__init__
    def short_vendor_timeout(self, *args, **kwargs):
        initialize(self, *args, timeout=.05, interval=.001)
    monkeypatch.setattr(VenusPhysicalExecutionInteractor, '__init__', short_vendor_timeout)

    factory = HamiltonOSDeviceFactory()
    app = OSApplicationFactory({'hamilton-venus': factory}).build(context)
    try:
        from culsma_os.console.adapters.mcp import MCPServerAdapter
        adapter = MCPServerAdapter(None, None, None)
        class PermissionService:
            def execute(self, credential, request):
                return factory.build_physical_permission(context)(request.get('enabled'))
        adapter.station_service = PermissionService()
        adapter.raw_credential = 'test'
        assert adapter.physical_execution_status()['enabled'] is False
        assert adapter.set_physical_execution(True)['enabled'] is True
        assert not vendor.calls

        run_id, loading = SetupFixture.submit(app, compiled)
        app.client.begin_setup(run_id, loading['fingerprint'])
        app.client.confirm_setup(run_id, loading['fingerprint'], True, 'operator_attestation')
        expected = ('cancelled' if fault in ('monitor-empty', 'monitor-missing') else
                    'needs_reconciliation' if fault in ('lost-load', 'missing-cleanup') else 'completed')
        observed = app.client.run_until_settled(run_id)
        assert observed.status == expected, observed
        assert sum(path == 'start' for _, path, _ in vendor.calls) == (0 if fault == 'lost-load' else 1)
        material = app.client.lifecycle.operations.material.get(run_id)
        assert material[0] == 'physical' and material[2] == (2 if expected == 'completed' else 0)
        usage = app.client.lifecycle.operations.evidence
        assert sum(usage.known_consumption(config['device_id'], mode='physical').values()) == (
            2 if expected in ('completed', 'cancelled') else 0)
        if expected == 'cancelled':
            assert not app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.reservations.get(run_id).status == 'released'
    finally:
        app.close()
