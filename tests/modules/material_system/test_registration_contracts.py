import sqlite3

import pytest

from culsma_os.material_system.models import MaterialCommitProposal
from culsma_os.material_system.repositories.local import LocalMaterialRepository


class TestRegistrationContracts:
    @pytest.fixture
    def ledger(self):
        connection = sqlite3.connect(':memory:')
        repository = LocalMaterialRepository(connection)
        repository.bind('run', 'simulation', {'quantity': 100})
        yield repository
        connection.close()

    def test_registration_replay_is_idempotent(self, ledger):
        values = ('run', 'simulation', 'effect', 'evidence', {'quantity': 100}, {'quantity': 80}, 'fingerprint')
        first = ledger.commit_once(*values)
        repeated = ledger.commit_once(*values)
        assert first == repeated and first.version == 1
        assert ledger.get('run') == ('simulation', {'quantity': 80}, 1)

    @pytest.mark.parametrize('mode,state', [('physical', {'quantity': 100}), ('simulation', {'quantity': 90})])
    def test_rebinding_cannot_reset_authoritative_state(self, ledger, mode, state):
        with pytest.raises(ValueError, match='MATERIAL_STATE_CONFLICT'):
            ledger.bind('run', mode, state)
        assert ledger.get('run') == ('simulation', {'quantity': 100}, 0)

    def test_conflicting_receipt_does_not_replace_registration(self, ledger):
        first = ledger.commit_once('run', 'simulation', 'effect', 'evidence', {'quantity': 100}, {'quantity': 80}, 'state')
        with pytest.raises(ValueError, match='MATERIAL_REGISTRATION_CONFLICT'):
            ledger.commit_once('run', 'simulation', 'effect', 'different', {'quantity': 100}, {'quantity': 80}, 'state')
        assert ledger.receipt('effect') == first
        assert ledger.get('run') == ('simulation', {'quantity': 80}, 1)

    def test_group_registration_rolls_back_every_member(self, ledger):
        proposals = (
            MaterialCommitProposal('one', 'e1', {'quantity': 100}, {'quantity': 80}, '80'),
            MaterialCommitProposal('two', 'e2', {'quantity': 70}, {'quantity': 50}, '50'),
        )
        with pytest.raises(ValueError, match='MATERIAL_VERSION_CONFLICT'):
            ledger.commit_group_once('run', 'simulation', proposals)
        assert ledger.get('run') == ('simulation', {'quantity': 100}, 0)
        assert ledger.receipt('one') is None and ledger.receipt('two') is None

    def test_group_commit_and_replay_keep_one_version_per_member(self, ledger):
        proposals = (
            MaterialCommitProposal('one', 'e1', {'quantity': 100}, {'quantity': 80}, '80'),
            MaterialCommitProposal('two', 'e2', {'quantity': 80}, {'quantity': 50}, '50'),
        )
        first = ledger.commit_group_once('run', 'simulation', proposals)
        assert [r.version for r in first] == [1, 2]
        assert ledger.commit_group_once('run', 'simulation', proposals) == first
        assert ledger.get('run') == ('simulation', {'quantity': 50}, 2)

    @pytest.mark.parametrize('duplicate', [False, True])
    def test_invalid_group_has_no_partial_registration(self, ledger, duplicate):
        proposal = MaterialCommitProposal('one', 'e1', {'quantity': 100}, {'quantity': 80}, '80')
        with pytest.raises(ValueError, match='COLLECTIVE_MATERIAL_PROPOSALS_INVALID'):
            ledger.commit_group_once('run', 'simulation', (proposal, proposal) if duplicate else ())
        assert ledger.get('run') == ('simulation', {'quantity': 100}, 0)
        assert ledger.receipt('one') is None
