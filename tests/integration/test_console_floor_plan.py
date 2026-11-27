from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness, ConsoleProtocolHarness
from tests.support.console.programs import session_headers


def test_floor_plan_catalogue_uses_configured_instances():
    from types import SimpleNamespace
    from culsma_os.workspace_manager.floor_plan import StationFloorPlanInteractor

    snapshot = SimpleNamespace(
        device_id='station',
        instrument_drivers={'centrifuge': ('centrifuge',), 'shaker': ('thermal_hold', 'orbital_shake'),
                            'incubator': ('thermal_hold',), 'washer': ('wash',)},
        processing_capabilities={'centrifuge': {'rotor': {}}, 'orbital_shake': {'heater-shaker': {}},
                                 'thermal_hold': {'heater-shaker': {}, 'untyped': {},
                                                  'cabinet': {'instrument_kind': 'incubator'}}},
    )
    interactor = StationFloorPlanInteractor(
        None, None, SimpleNamespace(config_path='fixture'),
        SimpleNamespace(execute=lambda path: snapshot),
    )
    assert {row['name']: row['kind'] for row in interactor.catalogue().values()} == {
        'rotor': 'centrifuge', 'heater-shaker': 'shaker', 'cabinet': 'incubator',
    }


def test_floor_plan_save_check_apply_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv('CULSMA_OS_STATION_ROOT', str(tmp_path / 'stations'))
    plan = {
        'areas': [{'id': 'rear', 'name': 'Rear extension', 'x': 0, 'y': -30, 'width': 100, 'height': 30}],
        'equipment': [{'id': 'washer', 'name': 'BioTek washer', 'kind': 'washer', 'area_id': 'rear',
                       'x': 20, 'y': 50, 'instrument': None, 'handoff': 'WA'}],
    }
    metric = {
        'deck': {'width': 1215, 'height': 497},
        'areas': [
            {'id': 'rear', 'name': 'Rear extension', 'x': 0, 'y': -700,
             'width': 1215, 'height': 700, 'level': 'deck'},
            {'id': 'lower', 'name': 'Lower shelf', 'x': 0, 'y': 0,
             'width': 1215, 'height': 497, 'level': 'below'},
        ],
        'equipment': [
            {**plan['equipment'][0], 'x': 250, 'y': 300, 'width': 550, 'height': 350},
        ],
    }
    endpoint = '/api/v1/configuration/floor-plan'
    with ConsoleProtocolHarness(tmp_path, 'transfer') as resident:
        server = ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint, 0, tmp_path / 'drafts.sqlite3'))
        with ConsoleHTTPHarness(server) as console:
            headers = session_headers(console)

            def send(action, previous=None, expected=200, **extra):
                payload = {'action': action, **extra}
                if previous is not None:
                    payload.update(revision=previous['revision'],
                                   configuration_fingerprint=previous['configuration_fingerprint'])
                status, _, body = console.request('POST', endpoint, headers, payload)
                assert status == expected, body
                return body['data'] if status == 200 else body['error']['code']

            initial = send('read')
            assert console.request('POST', endpoint,
                                   {k: v for k, v in headers.items() if k != 'Authorization'},
                                   {'action': 'read'})[0] == 401
            assert initial['applied'] is None
            overlap = {**plan, 'areas': [{**plan['areas'][0], 'y': -15}]}
            assert send('save', initial, expected=409, plan=overlap) == 'FLOOR_PLAN_AREA_OVERLAP'
            saved = send('save', initial, plan=plan)
            assert send('save', initial, expected=409, plan=plan) == 'FLOOR_PLAN_REVISION_CONFLICT'
            assert send('apply', saved, expected=409) == 'FLOOR_PLAN_CHECK_REQUIRED'
            assert 'floor_plan' not in resident.client.execute({'action': 'layout-status'})
            checked = send('check', saved)
            applied = send('apply', checked)
            assert applied['applied'] == plan
            layout = console.request('GET', '/api/v1/station', headers)[2]['data']['layout']
            assert layout['floor_plan']['equipment'] == plan['equipment']
            assert layout['floor_plan']['physical_observation'] is False
            assert layout['configuration_fingerprint'] == initial['configuration_fingerprint']
            outside = {**metric, 'equipment': [{**metric['equipment'][0], 'y': 400}]}
            assert send('save', applied, expected=409, plan=outside) == 'FLOOR_PLAN_EQUIPMENT_OUTSIDE'
            collision = {**metric, 'equipment': [
                metric['equipment'][0], {**metric['equipment'][0], 'id': 'another', 'x': 251},
            ]}
            assert send('save', applied, expected=409, plan=collision) == 'FLOOR_PLAN_EQUIPMENT_OVERLAP'
            saved_metric = send('save', applied, plan=metric)
            checked_metric = send('check', saved_metric)
            assert send('apply', checked_metric)['applied'] == metric
            assert resident.client.execute({'action': 'runs'})['runs'] == []
    with ConsoleProtocolHarness(tmp_path, 'transfer') as restarted:
        view = restarted.client.execute({'action': 'layout-status'})['floor_plan']
        assert view['deck'] == metric['deck']
        assert view['areas'] == metric['areas']
        assert view['equipment'] == metric['equipment']
        assert view['configuration_current'] is True
