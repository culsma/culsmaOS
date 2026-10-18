"""Language-owned no-motion effects complete without pretending a robot acted."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import ast
import json
import sqlite3
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from culsma_os.event_journal.models import AttemptRecord
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER
from tests.support.transfer_engine.plate96 import PlateFixture
from tests.support.transfer_engine.multichannel import MultichannelOSFixture, SOURCE as COLUMN_SOURCE


class NoActionFixture:
    def build(self, directory, body, load=f'{BUFFER}:200uL'):
        fixture=TransferMatrixFixture()
        plan=fixture.compile(fixture.source(body,load),directory)
        context=fixture.context(directory,plan)
        return plan,context,OSApplicationFactory().build(context)

    def pending(self,app,plan):
        app.client.start()
        identity=app.client.submit_run(RunRequest(plan,init_state(plan)))
        app.client.lifecycle.runs.advance_ready(identity)
        return identity,app.client.execution.pending(identity)

    def assert_complete(self,app,plan,result,logical_count,physical_count):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan,StubDriver(),init_state(plan))
        assert baseline.ok and result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        backend=app.host.gateway.port.session.backend
        assert len(backend.receipts)==physical_count
        assert backend.available_tips()==96-physical_count
        assert not app.client.lifecycle.operations.resource.occupied()
        run_id=result.user_result['os']['run_id']
        assert app.host.material.get(run_id)[1]==result.state.artifacts['material_state']
        owner=app.client.lifecycle.reservations.get(run_id)
        assert owner is not None and owner.status=='released'
        conn=app.host.material.repository.connection
        assert conn.execute('SELECT count(*) FROM os_logical_completions').fetchone()[0]==logical_count
        for (payload,) in conn.execute('SELECT record FROM os_logical_completions'):
            record=json.loads(payload)
            assert record['payload']=={'completion_kind':'logical','device_action':False}
            assert conn.execute('SELECT count(*) FROM os_attempts WHERE effect_id=?',(record['effect_id'],)).fetchone()[0]==0
            assert conn.execute('SELECT count(*) FROM os_evidence WHERE effect_id=?',(record['effect_id'],)).fetchone()[0]==0
        return run_id
