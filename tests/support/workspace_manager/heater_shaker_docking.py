"""Run-owned adapter access and motion compose with existing thermal and agitation effects."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import ast
import json
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.workspace_manager.labware_motion import MotionFixture
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER


BASE = f'''let p=plate(label="Assay",format="96well",capacity=200uL);
let wells=p[A1];
let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:100uL]);
wells[0] << [stock:50uL];
'''


HEAT = 'with env(thermal=37C,duration=1s) { hold(sample=wells); }\n'


SHAKE = 'agit(sample=wells[0],mode=shake,motion=orbital,rate=500rpm,duration=1s);\n'


TAIL = 'stock << [wells[0]:20uL];\nreturn wells[0];\n'


SOURCE = BASE + HEAT + SHAKE + TAIL


class HeaterShakerDockingFixture:
    def build(self, directory, change=None, shake_only=False):
        source = BASE + ('' if shake_only else HEAT) + SHAKE + TAIL
        plan = TransferMatrixFixture().compile(source, directory)
        first = next(s for p in plan.plans for s in p.steps if s.op in {'env_hold','agit'})
        last = [s for p in plan.plans for s in p.steps if s.op == 'Mutation'][-1]
        def configure(raw):
            raw['labware']['stock']['slot'] = 'B1'
            raw['modules'] = {'heater': {'model':'heaterShakerModuleV1','slot':'C1',
                                        'adapter':'opentrons_96_flat_bottom_adapter'}}
            raw['labware_moves'] = {first.step_id:[{'labware':'assay','destination':'module:heater'}],
                                   last.step_id:[{'labware':'assay','destination':'D1'}]}
            if change: change(raw)
        return MotionFixture().build(directory, configure, source)
