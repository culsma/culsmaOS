"""Whole-carrier docking and processing share the OS evidence and reservation chain."""

from pathlib import Path
import ast
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.workspace_manager.labware_motion import MotionFixture
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER


SOURCE = f'''let p=plate(label="Assay",format="96well",capacity=200uL);
let wells=p[A1];
let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:100uL]);
wells[0] << [stock:50uL];
with env(thermal=37C,duration=1s) {{ hold(sample=wells); }}
stock << [wells[0]:20uL];
return wells[0];'''


class DockingFixture:
    def build(self, directory, change=None):
        plan = TransferMatrixFixture().compile(SOURCE, directory)
        hold = next(s for p in plan.plans for s in p.steps if s.op == 'env_hold')
        mutations = [s for p in plan.plans for s in p.steps if s.op == 'Mutation']
        def configure(raw):
            raw['labware']['stock']['slot'] = 'B1'
            raw['modules'] = {'heater': {'model':'temperature module gen2','slot':'C1'}}
            raw['labware_moves'] = {hold.step_id:[{'labware':'assay','destination':'module:heater'}],
                mutations[-1].step_id:[{'labware':'assay','destination':'D1'}]}
            if change: change(raw)
        return MotionFixture().build(directory, configure, SOURCE)
