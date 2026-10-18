"""Functional expansion through the official virtual module and existing OS evidence chain."""

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
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER


DECLARATIONS = f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let p=plate(format="96well",capacity=100uL); let w=p[A1];'


HOLD = 'with env(thermal=37C,duration=1min) { hold(sample=w[0]); }'


SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + HOLD + ' stock << [w[0]:20uL];'


class ThermalFixture:
    def build(self, directory, source=SOURCE, configure=None):
        fixture = TransferMatrixFixture()
        plan = fixture.compile(source, directory)
        def configuration(raw):
            raw['modules'] = {'temperature': {'model': 'temperature module gen2', 'slot': '3'}}
            raw['labware']['assay'] = {'load_name': 'opentrons_96_aluminumblock_nest_wellplate_100ul', 'module': 'temperature'}
            allocations = [s for p in plan.plans for s in p.steps if s.op == 'AllocContainer']
            raw['bindings'] = {s.step_id: {'labware': 'tubes' if i == 0 else 'assay', 'well': 'A1' if i < 2 else 'B1'} for i,s in enumerate(allocations)}
            if configure:
                configure(raw)
        context = fixture.context(directory, plan, config_mutation=configuration)
        return plan, context, OSApplicationFactory().build(context)

    def waiting_hold(self, app, plan):
        app.client.start()
        identity = app.client.submit_run(RunRequest(plan, init_state(plan)))
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(identity)
        lifecycle.operations.dispatch_ready(identity)
        lifecycle.runs.advance_ready(identity)
        pending = app.client.execution.pending(identity)
        assert pending.prepared.runtime_step.op == 'env_hold'
        return identity, pending
