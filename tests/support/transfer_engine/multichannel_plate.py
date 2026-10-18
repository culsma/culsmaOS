"""State-specific reorder admission and durable non-prefix wave registration."""

from copy import deepcopy
from dataclasses import replace
import ast
from pathlib import Path
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.multichannel import MultichannelOSFixture
from tests.support.transfer_engine.plate96 import BUFFER


SOURCE=f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:2000uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); assay[A1:H12] << [stock:20uL];'


class WholePlateFixture:
    def build(self, tmp_path, source=SOURCE, pipette='p20_multi_gen2'):
        return MultichannelOSFixture().build(tmp_path, source, pipette)

    def pending(self, app, plan):
        app.client.start()
        run_id=app.client.submit_run(RunRequest(plan,init_state(plan)))
        app.client.lifecycle.runs.advance_ready(run_id)
        return run_id,app.client.execution.pending(run_id)

    def volumes(self, app, run_id):
        state=app.client.lifecycle.operations.material.get(run_id)[1]
        return {c['metadata']['label']:c['volume_uL'] for c in state['containers'].values()}
