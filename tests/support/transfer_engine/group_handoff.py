"""End-to-end group submission, registration, resources and recovery."""

from dataclasses import replace
import pytest
from culsma.runtime.state import init_state
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest, PendingEffectGroup
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from tests.support.transfer_engine.plate96 import PlateFixture, BUFFER
from tests.support.program_manager.hosted_semantics import HostedRuntimeFixture as HostedTestFixture


SOURCE=f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:1000uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); assay[A1:H1] << [stock:20uL];'


class GroupFixture:
    def build(self,tmp_path):
        return PlateFixture().run_case(tmp_path,SOURCE,'p20_single_gen2')

    def pending(self,app,plan):
        app.client.start()
        run_id=app.client.submit_run(RunRequest(plan,init_state(plan)))
        app.client.lifecycle.runs.advance_ready(run_id)
        pending=app.client.execution.pending(run_id)
        assert isinstance(pending,PendingEffectGroup) and len(pending.members)==8
        return run_id,pending
