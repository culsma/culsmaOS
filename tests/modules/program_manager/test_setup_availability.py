import sqlite3
import pytest
from culsma_os.program_manager.interactors.setup import RunSetupRequestInteractor
from culsma_os.program_manager.repositories.setup import SqliteRunSetupRepository
from culsma_os.program_manager.repositories.runs import SqliteTaskRepository
from culsma_os.program_manager.models import ResidentCommand, RunRecord


def test_missing_plan_has_an_explicit_availability_with_real_persistence(tmp_path):
    connection=sqlite3.connect(tmp_path/'setup.sqlite3')
    repository=SqliteRunSetupRepository(connection)
    tasks=SqliteTaskRepository(connection)
    tasks.save(RunRecord('known','completed','checkpoint'))
    for supported,status in [(False,'not_applicable'),(True,'not_generated')]:
        owner=RunSetupRequestInteractor(repository,tasks,supported)
        value=owner.execute(ResidentCommand('setup-show',run_id='known'))
        assert value['supported'] is supported and value['status']==status and value['plan'] is None
        with pytest.raises(KeyError):owner.execute(ResidentCommand('setup-show',run_id='unknown'))
    with pytest.raises(ValueError,match='SETUP_NOT_SUPPORTED'):
        RunSetupRequestInteractor(repository,tasks,False).execute(ResidentCommand('setup-begin',run_id='known'))
    connection.close()
