"""One station placement ledger across separate program stores and artifact directories."""

from dataclasses import replace
from pathlib import Path
import json
import shutil
import sqlite3
import pytest
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from culsma_os.resource_manager.interactors import StationPathInteractor
from tests.support.integration.resident_docking import ResidentDockingHarness, ObservedMotionFactory
from tests.support.workspace_manager.labware_motion import MotionFixture


class StationFixture:
    def query(self, context):
        return OSApplicationFactory({}).build_device_inspector(context).execute()

    def second(self, directory, context):
        return replace(context, database_path=directory/'second.sqlite3', artifacts_dir=directory/'second-artifacts')

    def emulate_legacy_store(self, context):
        station=StationPathInteractor().database_path(context)
        shared=StationPathInteractor().device_state_directory(context)/'motion-state.json'
        legacy=context.artifacts_dir/'motion-state.json'
        legacy.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(shared,legacy)
        shared.unlink()
        with sqlite3.connect(station) as source, sqlite3.connect(context.database_path) as target:
            for table in ('os_labware_positions','os_motion_registrations'):
                schema=source.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
                target.execute(schema)
                rows=source.execute('SELECT * FROM '+table).fetchall()
                if rows:
                    target.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
                source.execute('DELETE FROM '+table)
            source.execute('DELETE FROM os_station_motion_intents')
            source.execute('DELETE FROM os_workspace_imports')
        return legacy
