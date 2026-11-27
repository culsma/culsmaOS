"""Device configuration flows through the same verified activation as rack edits."""
import json

from tests.support.integration.console_labware import native_station


def test_configure_cytomat_from_active_station(tmp_path, monkeypatch):
    station = native_station(tmp_path, monkeypatch)
    original = json.loads(station.context.config_path.read_text())
    original['processing'] = {'cytomat': {
        'module_id': 'cytomat', 'labware': ['DWP96_E4'], 'simulation_com_port': 1,
        'stacker': 1, 'level': 1, 'loading': 'declared_simulation_exchange_fixture',
        'end_environment': 'retain_requested',
        'environment': {'humidity_percent': 90, 'co2_percent': 5, 'o2_percent': 20},
    }}
    station.context.config_path.write_text(json.dumps(original))
    with station as shared:
        fingerprint = shared.client.execute({'action': 'configuration-status'})['active']['fingerprint']
        endpoint = '/api/v1/configuration/instruments'

        def send(action, fp=fingerprint, **extra):
            return shared.http.request('POST', endpoint, shared.headers, {
                'action': action, 'configuration_fingerprint': fp, **extra,
            })

        assert shared.http.request('POST', endpoint, {
            'Origin': shared.url, 'Content-Type': 'application/json',
        }, {'action': 'read', 'configuration_fingerprint': fingerprint})[0] == 401
        status, _, reply = send('read')
        assert status == 200, reply
        instruments = reply['data']['instruments']
        pipettor = next(row for row in instruments if row['kind'] == 'pipetting')
        assert pipettor['mount'] == {'kind': 'gantry'}
        assert pipettor['details']['Liquid class'] == original['execution']['liquid_class']
        cytomat = next(row for row in instruments if row['module_id'] == 'cytomat')
        floor = shared.client.execute({'action': 'floor-plan', 'floor_plan_request': {'action': 'read'}})
        assert cytomat['id'] in {row['id'] for row in floor['instruments']}
        assert next(f['value'] for f in cytomat['fields'] if f['id'] == 'humidity_percent') == 90
        assert send('prepare', instrument=cytomat['id'], values={'simulation_com_port': 9})[0] == 409
        assert send('prepare', instrument=cytomat['id'], values={'humidity_percent': 110})[0] == 409

        status, _, reply = send('prepare', instrument=cytomat['id'], values={'humidity_percent': 83})
        assert status == 200, reply
        draft = reply['data']['draft']
        assert set(reply['data']) == {'draft', 'configuration_fingerprint'}
        assert shared.client.execute({'action': 'configuration-status'})['active']['fingerprint'] == fingerprint
        status, _, reply = shared.http.request('POST', '/api/v1/configuration/activation', shared.headers, {
            'action': 'apply', **draft, 'expected_fingerprint': fingerprint, 'request_id': 'change-humidity',
        })
        assert status == 200, reply
        shared.wait(lambda: shared.client.execute({'action': 'configuration-status'})['receipt']['status'] == 'applied')
        active = shared.client.execute({'action': 'configuration-status'})['active']
        status, _, reply = send('read', fp=active['fingerprint'])
        assert status == 200, reply
        updated = next(row for row in reply['data']['instruments'] if row['id'] == cytomat['id'])
        assert {f['id']: f['value'] for f in updated['fields']} == {
            'humidity_percent': 83, 'co2_percent': 5, 'o2_percent': 20, 'com_port': None,
        }
        assert send('prepare', instrument=cytomat['id'], values={'humidity_percent': 80})[0] == 409
        assert json.loads(shared.context.config_path.read_text()) == original
        assert not shared.backend.calls

def test_magnetic_rack_uses_declared_plate_site_in_local_simulation(tmp_path, monkeypatch):
    station = native_station(tmp_path, monkeypatch)
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory

    path = station.context.config_path
    config = json.loads(path.read_text())
    plate = 'DWP96_E4'
    height = config['execution']['pipetting']['aspiration_height_mm']
    config['well_positions'][plate] = {'A1': 'A1'}
    config['processing'] = {'magnet': {
        'module_id': 'magnet', 'kind': 'passive_rack', 'execution': 'local_model_only',
        'labware': [plate], 'aspirate_height_mm': height,
    }}
    path.write_text(json.dumps(config))
    _, instruments = HamiltonOSDeviceFactory().build_instrument_settings().catalogue(path)
    magnet = next(row for row in instruments if row['module_id'] == 'magnet')
    assert magnet['mount'] == {'kind': 'deck_site', 'carrier': 'CAR_HHS_3DWP_0001', 'site': '4'}
    assert magnet['fields'] == []
    assert magnet['details']['Aspiration height (mm)'] == str(height)
