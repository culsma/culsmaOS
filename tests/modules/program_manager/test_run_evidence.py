import ast
import sqlite3
import pytest

from culsma_os.storage import ReadOnlyDatabaseSnapshot
from culsma_os.event_journal.interactors.inspection import EvidenceInspectionInteractor
from culsma_os.event_journal.repositories.inspection import SqliteEvidenceInspectionRepository
from culsma_os.material_system.interactors import MaterialInspectionInteractor
from culsma_os.material_system.repositories.inspection import SqliteMaterialInspectionRepository
from culsma_os.program_manager.interactors.run_evidence import RunEvidenceInteractor
from tests.support.program_manager.run_evidence import RunEvidenceFixture
from tests.support.paths import ROOT


@pytest.fixture
def records(tmp_path):
    fixture = RunEvidenceFixture(tmp_path)
    try:
        yield fixture
    finally:
        fixture.close()


def test_missing_evidence_store_stays_absent(tmp_path):
    path = tmp_path/'absent'/'records.sqlite3'
    snapshot = ReadOnlyDatabaseSnapshot(path)
    reader = RunEvidenceInteractor(snapshot,
        EvidenceInspectionInteractor(SqliteEvidenceInspectionRepository(snapshot)),
        MaterialInspectionInteractor(SqliteMaterialInspectionRepository(snapshot)))
    result = reader.execute('run-1')
    assert result['accounting'] == 'unavailable' and result['attempts'] == []
    assert not path.parent.exists()
    assert snapshot.connection is None


def test_run_evidence_inspection_does_not_write(records):
    records.attempt(); records.receipt(); records.registration()
    before = tuple(records.writer.iterdump())
    for _ in range(3):
        result = records.reader.execute('run-1')
        assert result['hardware_observed'] is False
        assert result['attempts'][0]['registration']['status'] == 'registered'
    assert tuple(records.writer.iterdump()) == before


@pytest.mark.parametrize('overrides,status,outcome', [
    ({},'recorded','completed'), ({'outcome':'rejected'},'recorded','rejected'),
    ({'outcome':'unknown'},'recorded','unknown'),
    ({'attempt':'wrong-attempt'},'mismatched',None),
    ({'run':'another-run'},'mismatched',None), ({'mode':'physical'},'mismatched',None),
])
def test_receipt_identity_and_outcome_are_preserved(records, overrides, status, outcome):
    records.attempt(); records.receipt(**overrides)
    item = records.reader.execute('run-1')['attempts'][0]
    assert item['evidence_status'] == status
    assert (item['evidence']['outcome'] if item['evidence'] else None) == outcome


def test_missing_receipt_is_not_reported_as_rejection(records):
    records.attempt()
    item = records.reader.execute('run-1')['attempts'][0]
    assert item['evidence_status'] == 'missing' and item['evidence'] is None
    assert item['registration']['status'] == 'not_recorded'


@pytest.mark.parametrize('outcome,identity,expected', [
    ('completed',None,'registered'), ('completed','different-receipt','unmatched'),
    ('unknown',None,'unmatched'), ('rejected',None,'unmatched'),
])
def test_registration_requires_matching_completion(records, outcome, identity, expected):
    records.attempt(); records.receipt(outcome=outcome); records.registration(evidence=identity)
    item = records.reader.execute('run-1')['attempts'][0]
    assert item['registration']['status'] == expected


def test_logical_and_collective_evidence_keep_their_provenance(records):
    records.attempt()
    records.receipt(payload={'evidence_scope':'derived_wave_member', 'shared_evidence_id':'wave-receipt'})
    records.registration()
    records.add('os_logical_completions', dict(completion_id='logical-id', run_id='run-1', effect_id='no-action',
        mode='simulation', prepared_fingerprint='a', before_fingerprint='b', proposed_state_fingerprint='c',
        payload={'completion_kind':'logical','device_action':False}))
    records.registration('no-action','logical-id')
    view = records.reader.execute('run-1')
    assert len(view['attempts']) == len(view['logical_completions']) == 1
    assert view['attempts'][0]['evidence']['payload']['evidence_scope'] == 'derived_wave_member'
    logical = view['logical_completions'][0]
    assert logical['payload']['device_action'] is False
    assert logical['registration']['status'] == 'registered'


def test_run_scope_and_record_order(records):
    records.attempt('first', attempt='z');records.attempt('second',attempt='a')
    records.attempt('foreign',run='other-run');records.receipt('foreign',run='other-run')
    records.add('os_logical_completions', dict(completion_id='foreign-logical',run_id='other-run',effect_id='foreign-logical',
        mode='simulation',prepared_fingerprint='a',before_fingerprint='b',proposed_state_fingerprint='c',payload={}))
    view = records.reader.execute('run-1')
    assert [x['effect_id'] for x in view['attempts']] == ['first','second']
    assert view['logical_completions'] == []
    assert view['ordering'] == 'insertion_order_within_each_record_kind'


def test_evidence_snapshot_is_consistent_during_commit(records):
    records.attempt(); records.receipt(); records.registration()
    class InterleavingJournal(EvidenceInspectionInteractor):
        def inspect_run(self, run_id):
            view = super().inspect_run(run_id)
            with records.writer:
                records.writer.execute("UPDATE os_material_changes SET receipt=replace(receipt,'receipt-effect-1','new-receipt')")
            return view
    reader = RunEvidenceInteractor(records.snapshot, InterleavingJournal(records.journal.repository), records.material)
    assert reader.execute('run-1')['attempts'][0]['registration']['status'] == 'registered'
    assert records.reader.execute('run-1')['attempts'][0]['registration']['status'] == 'unmatched'


def test_run_evidence_owner_boundaries():
    path = ROOT/'src/culsma_os/program_manager/interactors/run_evidence.py'
    source = path.read_text(); tree = ast.parse(source)
    imports = [n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any('repositories' in name or 'adapters' in name for name in imports)
    assert 'sqlite3' not in source
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not calls & {'commit_once','reconcile','ingest','record_intent','dispatch','advance','register'}
    for module in ['event_journal/repositories/inspection.py','material_system/repositories/inspection.py']:
        source = (ROOT/'src/culsma_os'/module).read_text()
        assert not any(word in source for word in ['INSERT ', 'UPDATE ', 'CREATE TABLE', 'DELETE '])
