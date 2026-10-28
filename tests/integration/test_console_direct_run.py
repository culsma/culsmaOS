"""One durable start command owns automatic simulation preparation and failures."""
import sqlite3
import pytest
from tests.support.integration.shared_setup import SharedSetupHarness


def start(shared, request_id='direct-run'):
    status, _, body = shared.http.request('POST','/api/v1/programs',shared.headers,
        {'action':'inspect','program_id':'transfer.culs'})
    assert status == 200 and body['data']['valid']
    payload = {'action':'start','program_id':'transfer.culs','snapshot_id':body['data']['snapshot_id'],'request_id':request_id}
    status, _, body = shared.http.request('POST','/api/v1/programs',shared.headers,payload)
    assert status == 200, body
    return payload, body['data']['run']['run_id']


def test_direct_simulation_start_completes_without_operator_commands_and_is_idempotent(tmp_path):
    with SharedSetupHarness(tmp_path,submit=False,programs=True) as shared:
        payload, run_id = start(shared)
        shared.wait(lambda:shared.status(run_id)['status']=='completed')
        setup = shared.client.execute({'action':'setup-show','run_id':run_id})
        assert setup['confirmation']['source'] == 'simulation_fixture'
        assert setup['confirmation']['physical_observation'] is False
        assert not setup['activity']
        for _ in range(2):
            status, _, repeated = shared.http.request('POST','/api/v1/programs',shared.headers,payload)
            assert status == 200 and repeated['data']['run']['run_id'] == run_id
        assert len(shared.client.execute({'action':'runs'})['runs']) == 1
        assert len(shared.backend.calls) == 2
        with sqlite3.connect(shared.context.database_path) as db:
            assert db.execute('SELECT startup FROM os_run_queue WHERE run_id=?',(run_id,)).fetchone()[0]=='automatic'
        # Changing startup behavior under a retained request identity is rejected.
        assert shared.http.request('POST','/api/v1/programs',shared.headers,{**payload,'action':'submit'})[0] == 409


def test_failed_automatic_preparation_settles_and_next_program_can_run(tmp_path):
    with SharedSetupHarness(tmp_path,submit=False,programs=True) as shared:
        source = shared.program_root / 'transfer.culs'
        original = source.read_text()
        source.write_text(original.replace('capacity = 2000uL','capacity = 2000000uL'))
        _, run_id = start(shared,'too-large')
        shared.wait(lambda:shared.status(run_id)['status']=='failed')
        failed = shared.status(run_id)
        assert failed['body_outcome'] == 'failed' and failed['error']
        assert not shared.backend.calls
        source.write_text(original)
        _, next_id = start(shared,'corrected')
        shared.wait(lambda:shared.status(next_id)['status']=='completed')
        assert len(shared.backend.calls) == 2


def test_automatic_start_retains_unknown_execution_without_repeating_it(tmp_path):
    shared=SharedSetupHarness(tmp_path,submit=False,programs=True)
    shared.backend.outcome='unknown'
    with shared:
        payload,run_id=start(shared,'unknown-result')
        shared.wait(lambda:shared.status(run_id)['status']=='needs_reconciliation')
        for _ in range(2):
            status,_,body=shared.http.request('POST','/api/v1/programs',shared.headers,payload)
            assert status==200 and body['data']['run']['run_id']==run_id
        _,successor=start(shared,'after-unknown')
        assert shared.status(successor)['status']=='ready'
        assert shared.status(run_id)['status']=='needs_reconciliation'
        assert len(shared.backend.calls)==1
