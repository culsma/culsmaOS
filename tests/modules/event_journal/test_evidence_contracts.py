from dataclasses import replace
import sqlite3

import pytest

from culsma_os.driver_framework.models import DeviceReceipt
from culsma_os.event_journal.interactors.evidence import EvidenceInteractor
from culsma_os.event_journal.models import AttemptRecord, LogicalCompletion
from culsma_os.event_journal.repositories.evidence import SqliteEvidenceRepository
from culsma_os.event_journal.repositories.events import SqliteRunEventRepository


class TestEvidenceContracts:
    @pytest.fixture
    def journal(self):
        connection = sqlite3.connect(':memory:')
        interactor = EvidenceInteractor(SqliteEvidenceRepository(connection), SqliteRunEventRepository(connection))
        yield interactor
        connection.close()

    @pytest.fixture
    def attempt(self):
        return AttemptRecord('attempt', 'run', 'effect', 'simulation',
                             {'step_id': 'step', 'configuration_revision': 'rev', 'device_id': 'device'})

    @pytest.fixture
    def receipt(self):
        return DeviceReceipt('completed', 'simulation', 'step', 'rev', {'observed': True}, {'tips': 1})

    @pytest.fixture
    def logical(self):
        return LogicalCompletion('logical', 'run', 'effect', 'simulation', 'prepared', 'before', 'after',
                                 {'device_action': False, 'completion_kind': 'logical'})

    def test_confirmed_receipt_retains_attempt_identity(self, journal, attempt, receipt):
        evidence = journal.normalize(attempt, receipt)
        assert (evidence.attempt_id, evidence.run_id, evidence.effect_id) == ('attempt', 'run', 'effect')
        assert evidence.outcome == 'completed' and evidence.payload == receipt.payload
        assert evidence.consumed_resources == {'tips': 1}

    @pytest.mark.parametrize('field,value', [('mode', 'physical'), ('step_id', 'other'), ('configuration_revision', 'other')])
    def test_mismatched_identity_cannot_confirm_success(self, journal, attempt, receipt, field, value):
        evidence = journal.normalize(attempt, replace(receipt, **{field: value}))
        assert evidence.outcome == 'unknown'
        assert evidence.consumed_resources == {'tips': 1}

    def test_acknowledgement_is_not_completion(self, journal, attempt, receipt):
        with pytest.raises(ValueError, match='EVIDENCE_OUTCOME_INVALID'):
            journal.normalize(attempt, replace(receipt, outcome='acknowledged'))

    def test_duplicate_receipt_does_not_double_count_consumption(self, journal, attempt, receipt):
        journal.repository.record_intent(attempt)
        evidence = journal.normalize(attempt, receipt)
        journal.ingest(evidence)
        journal.ingest(evidence)
        assert journal.known_consumption('device') == {'tips': 1}
        with pytest.raises(ValueError, match='EVIDENCE_CONFLICT'):
            journal.ingest(replace(evidence, consumed_resources={'tips': 2}))
        assert journal.find_evidence('effect') == evidence
        assert journal.known_consumption('device') == {'tips': 1}

    @pytest.mark.parametrize('field,value', [('attempt_id', 'wrong'), ('run_id', 'wrong'), ('mode', 'physical')])
    def test_unowned_receipt_does_not_enter_journal(self, journal, attempt, receipt, field, value):
        journal.repository.record_intent(attempt)
        evidence = replace(journal.normalize(attempt, receipt), **{field: value})
        with pytest.raises(ValueError, match='EVIDENCE_ATTEMPT_MISMATCH'):
            journal.ingest(evidence)
        assert journal.find_evidence('effect') is None
        assert journal.known_consumption('device') == {}

    @pytest.mark.parametrize('changes', [
        {'mode': 'physical'},
        {'payload': {'device_action': True, 'completion_kind': 'logical'}},
        {'payload': {'device_action': False, 'completion_kind': 'device'}},
    ])
    def test_logical_completion_cannot_claim_a_device_action(self, journal, logical, changes):
        with pytest.raises(ValueError, match='LOGICAL_COMPLETION_INVALID'):
            journal.record_logical_completion(replace(logical, **changes))
        assert journal.find_completion('effect') is None

    @pytest.mark.parametrize('first', ['logical', 'physical'])
    def test_logical_and_physical_intents_are_mutually_exclusive(self, journal, logical, attempt, first):
        if first == 'logical':
            journal.record_logical_completion(logical)
            with pytest.raises(ValueError, match='LOGICAL_PHYSICAL_CONFLICT'):
                journal.repository.record_intent(attempt)
            assert journal.find_completion('effect') == logical
        else:
            journal.repository.record_intent(attempt)
            with pytest.raises(ValueError, match='LOGICAL_PHYSICAL_CONFLICT'):
                journal.record_logical_completion(logical)
            assert journal.find_logical_completion('effect') is None
            assert journal.find_attempt('effect') == attempt
