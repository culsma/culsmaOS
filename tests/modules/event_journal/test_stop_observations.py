import sqlite3
from unittest.mock import Mock
import pytest
from culsma_os.event_journal.repositories.evidence import SqliteEvidenceRepository
from culsma_os.event_journal.interactors.evidence import EvidenceInteractor
from culsma_os.event_journal.models import AttemptRecord, ExecutionEvidence


def test_stop_observation_is_separate_durable_and_reserves_unknown_consumption():
    db = sqlite3.connect(':memory:')
    repository = SqliteEvidenceRepository(db)
    journal = EvidenceInteractor(repository, Mock())
    attempt = AttemptRecord('attempt', 'run', 'effect', 'physical',
        {'device_id': 'robot', 'description': {'resource_requirements': {'tips': 2}}})
    repository.record_intent(attempt)
    receipt = ExecutionEvidence('receipt', 'run', 'effect', 'attempt', 'physical', 'unknown', {}, {'tips': 1})
    journal.ingest(receipt)
    proof = {'attempt_id': 'attempt', 'mode': 'physical', 'state': 'stopped', 'evidence_ref': 'agent-job'}
    assert not journal.cancellation_requested('run')
    with pytest.raises(ValueError, match='ATTEMPT_STOP_INVALID'):
        journal.record_stop(attempt, proof)
    journal.request_cancellation('run')
    journal.request_cancellation('run')
    assert journal.cancellation_requested('run')
    stop = journal.record_stop(attempt, proof)
    assert stop['reserved_consumption'] == {'tips': 1}
    assert journal.record_stop(attempt, proof) == stop
    assert journal.find_stop('attempt') == stop
    assert journal.find_evidence('effect') == receipt
    assert journal.known_consumption('robot', 'physical') == {'tips': 2}
    assert repository.find_stop('missing') is None
    with pytest.raises(ValueError, match='ATTEMPT_STOP_CONFLICT'):
        repository.record_stop('attempt', {**stop, 'mode': 'simulation'})
    restarted = EvidenceInteractor(SqliteEvidenceRepository(db), Mock(), Mock())
    restarted.synchronize_device_usage('robot')
    assert restarted.usage.record.call_count == 2
    assert restarted.find_stop('attempt') == stop
    db.close()


@pytest.mark.parametrize('field,value', [('attempt_id', 'other'), ('mode', 'physical'), ('state', 'running')])
def test_stop_must_match_attempt(field, value):
    repository = SqliteEvidenceRepository(sqlite3.connect(':memory:'))
    journal = EvidenceInteractor(repository, Mock())
    attempt = AttemptRecord('a', 'r', 'e', 'simulation', {'description': {}, 'device_id': 'robot'})
    repository.record_intent(attempt)
    journal.request_cancellation('r')
    proof = {'attempt_id': 'a', 'mode': 'simulation', 'state': 'stopped', 'evidence_ref': 'job', field: value}
    with pytest.raises(ValueError, match='ATTEMPT_STOP_INVALID'):
        journal.record_stop(attempt, proof)
