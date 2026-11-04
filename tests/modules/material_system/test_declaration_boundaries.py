"""Durable local declaration transitions use a real SQLite ledger."""
import sqlite3
import pytest
from culsma_os.material_system.repositories.local import LocalMaterialRepository


def test_local_declaration_repository_is_durable_idempotent_and_compare_and_swap(tmp_path):
    path=tmp_path/'ledger.sqlite3'
    before={'containers':{'one':{'volume_uL':1}}}
    after={'containers':{'one':{'volume_uL':1},'two':{'volume_uL':0}}}
    repo=LocalMaterialRepository(sqlite3.connect(path))
    repo.bind('run','simulation',before)
    assert repo.adopt_declarations('run','simulation','boundary',before,0,after,'before','after')==1
    repo.connection.close()
    repo=LocalMaterialRepository(sqlite3.connect(path))
    try:
        assert repo.adopt_declarations('run','simulation','boundary',before,0,after,'before','after')==1
        assert repo.get('run')==('simulation',after,1)
        with pytest.raises(ValueError,match='MATERIAL_DECLARATION_CONFLICT'):
            repo.adopt_declarations('run','simulation','boundary',before,0,after,'before','other')
        with pytest.raises(ValueError,match='MATERIAL_DECLARATION_CONFLICT'):
            repo.adopt_declarations('run','simulation','stale-boundary',before,0,after,'before','after')
        assert repo.get('run')==('simulation',after,1)
        assert repo.connection.execute('SELECT count(*) FROM os_material_changes').fetchone()[0]==0
    finally:repo.connection.close()
