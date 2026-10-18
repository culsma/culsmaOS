import json
from ..models import MaterialCommitReceipt


class LocalMaterialRepository:

    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_material(run_id TEXT PRIMARY KEY,mode TEXT,state TEXT,version INTEGER)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_material_changes(effect_id TEXT PRIMARY KEY,receipt TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_material_uncertainty(effect_id TEXT PRIMARY KEY,run_id TEXT,evidence_id TEXT)"
            )

    def bind(self, run_id, mode, state):
        encoded = json.dumps(state, sort_keys=True)
        with self.connection:
            row = self.connection.execute(
                "SELECT mode,state,version FROM os_material WHERE run_id=?", (run_id,)
            ).fetchone()
            if row:
                if row[:2] != (mode, encoded):
                    raise ValueError("MATERIAL_STATE_CONFLICT")
                return row[2]
            self.connection.execute(
                "INSERT INTO os_material VALUES(?,?,?,0)", (run_id, mode, encoded)
            )
            return 0

    def receipt(self, effect_id):
        row = self.connection.execute(
            "SELECT receipt FROM os_material_changes WHERE effect_id=?", (effect_id,)
        ).fetchone()
        return MaterialCommitReceipt(**json.loads(row[0])) if row else None

    def get(self, run_id):
        row = self.connection.execute(
            "SELECT mode,state,version FROM os_material WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return (row[0], json.loads(row[1]), row[2])

    def commit_once(
        self, run_id, mode, effect_id, evidence_id, before, after, fingerprint
    ):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            return self.commit_in_transaction(run_id, mode, effect_id, evidence_id, before, after, fingerprint)

    def commit_group_once(self, run_id, mode, proposals):
        if not proposals or len({p.effect_id for p in proposals}) != len(proposals):
            raise ValueError("COLLECTIVE_MATERIAL_PROPOSALS_INVALID")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            return tuple(self.commit_in_transaction(run_id, mode, p.effect_id, p.evidence_id,
                                                    p.before, p.after, p.fingerprint, p.semantic_state_fingerprint) for p in proposals)

    def commit_in_transaction(self, run_id, mode, effect_id, evidence_id, before, after, fingerprint, semantic_fingerprint=None):
        existing = self.receipt(effect_id)
        if existing:
            if (
                existing.evidence_id != evidence_id
                or existing.proposed_state_fingerprint != fingerprint
                or (existing.semantic_state_fingerprint or existing.proposed_state_fingerprint) != (semantic_fingerprint or fingerprint)
            ):
                raise ValueError("MATERIAL_REGISTRATION_CONFLICT")
            return existing
        stored_mode, state, version = self.get(run_id)
        if stored_mode != mode or state != before:
            raise ValueError("MATERIAL_VERSION_CONFLICT")
        receipt = MaterialCommitReceipt(
            f"{effect_id}:material",
            effect_id,
            evidence_id,
            version + 1,
            fingerprint,
            semantic_fingerprint,
        )
        changed = self.connection.execute(
            "UPDATE os_material SET state=?,version=version+1 WHERE run_id=? AND version=?",
            (json.dumps(after, sort_keys=True), run_id, version),
        ).rowcount
        if changed != 1:
            raise ValueError("MATERIAL_VERSION_CONFLICT")
        self.connection.execute(
            "INSERT INTO os_material_changes VALUES(?,?)",
            (effect_id, json.dumps(receipt.__dict__, sort_keys=True)),
        )
        return receipt

    def mark_uncertain(self, run_id, effect_id, evidence_id):
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO os_material_uncertainty VALUES(?,?,?)",
                (effect_id, run_id, evidence_id),
            )

    def uncertainties(self, run_id):
        return tuple(
            (
                row[0]
                for row in self.connection.execute(
                    "SELECT effect_id FROM os_material_uncertainty WHERE run_id=? ORDER BY effect_id",
                    (run_id,),
                )
            )
        )
