"""Material-owned read-only registration receipts; never initialize tables."""
import json
from typing import Protocol
from ..models import MaterialCommitReceipt


class MaterialInspectionRepository(Protocol):
    def receipt(self, effect_id) -> MaterialCommitReceipt | None: ...


class SqliteMaterialInspectionRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def receipt(self, effect_id):
        rows = self.snapshot.rows('os_material_changes',
            'SELECT receipt FROM os_material_changes WHERE effect_id=?', (effect_id,))
        return MaterialCommitReceipt(**json.loads(rows[0][0])) if rows else None
