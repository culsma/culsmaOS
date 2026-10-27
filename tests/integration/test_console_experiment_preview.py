"""Preview is an offline proposal; confirmed loading remains the dispatch gate."""
import json
from tests.support.integration.shared_setup import SharedSetupHarness


def preview(shared):
    code, _, body = shared.http.request('POST', '/api/v1/programs', shared.headers,
                                       {'action':'preview', 'program_id':'transfer.culs'})
    assert code == 200, body
    return body['data']


def test_preview_matches_final_loading_without_admission_or_reservation(tmp_path):
    with SharedSetupHarness(tmp_path, submit=False, programs=True) as shared:
        before = shared.context.config_path.read_bytes()
        observed = shared.client.execute({'action':'device-status'})
        view = preview(shared)
        assert view['valid'] and view['preparation']['status'] == 'available'
        assert view['preparation']['physical_observation'] is False
        assert not shared.client.execute({'action':'runs'})['runs']
        after = shared.client.execute({'action':'device-status'})
        assert {k:v for k,v in after.items() if k!='observed_at'} == {k:v for k,v in observed.items() if k!='observed_at'}
        assert not shared.backend.calls
        assert shared.context.config_path.read_bytes() == before
        payload = {'action':'submit', 'program_id':'transfer.culs', 'snapshot_id':view['snapshot_id'],
                   'request_id':'from-preview', 'configuration_fingerprint':view['preparation']['configuration_fingerprint']}
        code, _, response = shared.http.request('POST','/api/v1/programs',shared.headers,payload)
        assert code == 200, response
        run = response['data']['run']['run_id']
        shared.wait(lambda:shared.status(run)['status']=='awaiting_setup')
        final = shared.client.execute({'action':'setup-show','run_id':run})
        for key in ('bindings','loadout','supplies','layout'):
            assert final[key] == view['preparation']['plan'][key]
        assert not shared.backend.calls
        assert shared.client.execute({'action':'device-status'})['resources']['station_reservations'] == []
        # A stale reviewed station must not admit a second experiment.
        payload.update(request_id='stale-preview', configuration_fingerprint='0'*64)
        assert shared.http.request('POST','/api/v1/programs',shared.headers,payload)[0] == 409
        assert len(shared.client.execute({'action':'runs'})['runs']) == 1


def test_unavailable_capacity_reports_requirements_without_creating_run(tmp_path):
    shared = SharedSetupHarness(tmp_path, submit=False, programs=True)
    config = json.loads(shared.context.config_path.read_text())
    config['execution']['capacities_uL'] = {name:1 for name in config['execution']['capacities_uL']}
    shared.context.config_path.write_text(json.dumps(config))
    with shared:
        view = preview(shared)
        assert view['preparation']['status'] == 'blocked'
        assert view['preparation']['diagnostic'] == 'SETUP_NO_FEASIBLE_LOCATION'
        assert view['preparation']['requirements'] and view['preparation']['plan'] is None
        assert not shared.client.execute({'action':'runs'})['runs'] and not shared.backend.calls


def test_preview_rejects_missing_auth_and_invalid_protocol_stays_unsubmitted(tmp_path):
    with SharedSetupHarness(tmp_path, submit=False, programs=True) as shared:
        assert shared.http.request('POST','/api/v1/programs',{'Origin':shared.url,'Content-Type':'application/json'},
            {'action':'preview','program_id':'transfer.culs'})[0] == 401
        (shared.program_root/'transfer.culs').write_text('not a valid protocol')
        view = preview(shared)
        assert not view['valid'] and 'preparation' not in view
        assert not shared.backend.calls and not shared.client.execute({'action':'runs'})['runs']


def test_preview_and_final_plan_reuse_configured_positions(tmp_path):
    shared = SharedSetupHarness(tmp_path, submit=False, programs=True)
    config = json.loads(shared.context.config_path.read_text())
    # Both tubes fit either location; the configured order deliberately differs
    # from catalogue order. Do not silently exchange source and destination.
    config['bindings'] = {'entry.s0::alloc': {'labware':'destination_plate','well':'1'},
                          'entry.s1::alloc': {'labware':'source_vessel','well':'1'}}
    shared.context.config_path.write_text(json.dumps(config))
    with shared:
        view = preview(shared)
        assert view['preparation']['plan']['bindings'] == config['bindings']
        code, _, response = shared.http.request('POST','/api/v1/programs',shared.headers,
            {'action':'submit','program_id':'transfer.culs','snapshot_id':view['snapshot_id'],
             'request_id':'preserve-sites','configuration_fingerprint':view['preparation']['configuration_fingerprint']})
        assert code == 200, response
        run = response['data']['run']['run_id']
        shared.wait(lambda:shared.status(run)['status']=='awaiting_setup')
        assert shared.client.execute({'action':'setup-show','run_id':run})['bindings'] == config['bindings']
        assert not shared.backend.calls
