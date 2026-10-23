import sqlite3
import pytest
from culsma_os.program_manager.repositories.setup import SqliteRunSetupRepository


def test_setup_repository_revisions_and_reopen_preserve_confirmation(tmp_path):
    path = tmp_path/'setup.sqlite3'
    connection = sqlite3.connect(path)
    repository = SqliteRunSetupRepository(connection)
    with pytest.raises(KeyError): repository.get('run')
    first = repository.save('run', {'phase':'planned', 'confirmation':None}, 0)
    assert first['revision']==1
    with pytest.raises(ValueError, match='SETUP_REVISION_CONFLICT'):
        repository.save('run', {'phase':'confirmed'}, 0)
    second = repository.save('run', {'phase':'confirmed','confirmation':{'source':'operator_attestation'}}, 1)
    with pytest.raises(ValueError, match='SETUP_REVISION_CONFLICT'):
        repository.save('run', {'phase':'planned'}, 1)
    connection.close()
    connection = sqlite3.connect(path)
    try:
        assert SqliteRunSetupRepository(connection).get('run')==second
    finally:
        connection.close()


def test_setup_command_receipts_are_idempotent_and_identity_bound():
    connection=sqlite3.connect(':memory:')
    repository=SqliteRunSetupRepository(connection)
    payload={'run_id':'run','action':'begin','fingerprint':'a'*64}
    try:
        first=repository.enqueue('request',payload)
        assert first['status']=='pending'
        assert repository.enqueue('request',payload)==first
        with pytest.raises(ValueError,match='SETUP_REQUEST_ID_CONFLICT'):
            repository.enqueue('request',{**payload,'run_id':'another'})
        assert len(repository.pending_requests())==1
        repository.settle_request('request',result={'phase':'loading'})
        assert not repository.pending_requests()
        assert repository.enqueue('request',payload)['result']=={'phase':'loading'}
        repository.settle_request('request',error='late overwrite')
        assert repository.request('request')['status']=='completed'
    finally:
        connection.close()


def test_shared_activity_is_run_scoped_bounded_and_preserves_failed_commands():
    with sqlite3.connect(':memory:') as connection:
        repository=SqliteRunSetupRepository(connection)
        for index in range(25):
            repository.enqueue(f'r{index}',{'run_id':'run','action':'revise','origin':'local-mcp-process'})
        repository.settle_request('r24',error='SETUP_PLAN_STALE')
        repository.enqueue('other',{'run_id':'another','action':'confirm','origin':'local-console-process'})
        activity=repository.activity('run')
        assert len(activity)==20 and activity[0]['request_id']=='r24' and activity[-1]['request_id']=='r5'
        assert activity[0]['status']=='failed' and activity[0]['error']=='SETUP_PLAN_STALE'
        assert all(row['origin']=='local-mcp-process' for row in activity)
        assert repository.activity('absent')==[]
