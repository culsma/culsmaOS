import json
import sqlite3
from pathlib import Path

from culsma_os.storage import ReadOnlyDatabaseSnapshot
from culsma_os.event_journal.interactors.inspection import EvidenceInspectionInteractor
from culsma_os.event_journal.repositories.inspection import SqliteEvidenceInspectionRepository
from culsma_os.material_system.interactors import MaterialInspectionInteractor
from culsma_os.material_system.repositories.inspection import SqliteMaterialInspectionRepository
from culsma_os.program_manager.interactors.run_evidence import RunEvidenceInteractor


class RunEvidenceFixture:
    def __init__(self, root):
        self.path = Path(root)/'records.sqlite3'
        self.writer = sqlite3.connect(self.path)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.executescript("""
            CREATE TABLE os_attempts(attempt_id TEXT PRIMARY KEY,effect_id TEXT UNIQUE,record TEXT);
            CREATE TABLE os_evidence(evidence_id TEXT PRIMARY KEY,effect_id TEXT UNIQUE,record TEXT);
            CREATE TABLE os_logical_completions(effect_id TEXT PRIMARY KEY,record TEXT);
            CREATE TABLE os_material_changes(effect_id TEXT PRIMARY KEY,receipt TEXT);
        """)
        self.snapshot = ReadOnlyDatabaseSnapshot(self.path)
        self.journal = EvidenceInspectionInteractor(SqliteEvidenceInspectionRepository(self.snapshot))
        self.material = MaterialInspectionInteractor(SqliteMaterialInspectionRepository(self.snapshot))
        self.reader = RunEvidenceInteractor(self.snapshot, self.journal, self.material)

    def add(self, table, value):
        with self.writer:
            if table == 'os_material_changes':
                self.writer.execute('INSERT INTO os_material_changes VALUES(?,?)', (value['effect_id'],json.dumps(value)))
            elif table == 'os_logical_completions':
                self.writer.execute('INSERT INTO os_logical_completions VALUES(?,?)', (value['effect_id'],json.dumps(value)))
            else:
                identity = value['attempt_id'] if table == 'os_attempts' else value['evidence_id']
                self.writer.execute('INSERT INTO '+table+' VALUES(?,?,?)', (identity,value['effect_id'],json.dumps(value)))

    def attempt(self, effect='effect-1', run='run-1', attempt='attempt-z'):
        self.add('os_attempts', dict(attempt_id=attempt, run_id=run, effect_id=effect, mode='simulation',
                 context={'device_id':'device-1', 'step_id':'step-1'}))

    def receipt(self, effect='effect-1', run='run-1', attempt='attempt-z', outcome='completed', mode='simulation', payload=None):
        self.add('os_evidence', dict(evidence_id='receipt-'+effect, run_id=run, effect_id=effect, attempt_id=attempt,
                 mode=mode, outcome=outcome, payload=payload or {}, consumed_resources={}))

    def registration(self, effect='effect-1', evidence=None):
        self.add('os_material_changes', dict(registration_id='registration-'+effect, effect_id=effect,
                 evidence_id=evidence or 'receipt-'+effect, version=1, proposed_state_fingerprint='fingerprint'))

    def close(self):
        self.writer.close()
