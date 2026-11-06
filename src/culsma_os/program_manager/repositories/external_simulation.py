"""Persist the external fixture request and its single accepted receipt."""

import json


class SqliteExternalSimulationRepository:
    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS os_external_simulation_handoffs (
                handoff_id TEXT PRIMARY KEY,
                source_run_id TEXT NOT NULL UNIQUE REFERENCES os_runs(run_id),
                request TEXT NOT NULL,
                continuation TEXT NOT NULL,
                receipt TEXT
            )""")

    def create(self, request, continuation):
        with self.connection:
            self.connection.execute(
                """INSERT INTO os_external_simulation_handoffs
                (handoff_id, source_run_id, request, continuation) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_run_id) DO NOTHING""",
                (request["handoff_id"], request["source_run_id"], json.dumps(request), continuation),
            )
        row = self.connection.execute(
            "SELECT handoff_id FROM os_external_simulation_handoffs WHERE source_run_id=?",
            (request["source_run_id"],),
        ).fetchone()
        return self.get(row[0])

    def get(self, handoff_id):
        row = self.connection.execute(
            "SELECT request, continuation, receipt FROM os_external_simulation_handoffs WHERE handoff_id=?",
            (handoff_id,),
        ).fetchone()
        if row is None:
            raise ValueError("EXTERNAL_HANDOFF_NOT_FOUND")
        request, continuation, receipt = row
        return json.loads(request), continuation, json.loads(receipt) if receipt is not None else None

    def accept(self, handoff_id, receipt):
        with self.connection:
            self.connection.execute(
                "UPDATE os_external_simulation_handoffs SET receipt=? WHERE handoff_id=? AND receipt IS NULL",
                (json.dumps(receipt, allow_nan=False), handoff_id),
            )
        return self.get(handoff_id)[2]
