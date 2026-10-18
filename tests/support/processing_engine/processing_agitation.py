"""Orbital agitation reuses the OS execution/evidence/material chain."""

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


DECLARATIONS = f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let p=plate(format="96well",capacity=200uL); let w=p[A1];'


SHAKE = 'agit(sample=w[0],mode=shake,motion=orbital,duration=30s,rate=500rpm);'


SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + SHAKE + ' stock << [w[0]:20uL];'


class AgitationFixture:
    def build(self, directory, source=SOURCE, configure=None):
        fixture = TransferMatrixFixture()
        plan = fixture.compile(source, directory)
        def configuration(raw):
            raw['modules'] = {'shaker': {'model': 'heaterShakerModuleV1', 'slot': '6'}}
            raw['labware']['assay'] = {'load_name': 'nest_96_wellplate_200ul_flat',
                                      'adapter': 'opentrons_96_flat_bottom_adapter', 'module': 'shaker'}
            allocations = [s for p in plan.plans for s in p.steps if s.op == 'AllocContainer']
            raw['bindings'] = {s.step_id: {'labware': 'tubes' if i == 0 else 'assay', 'well': 'A1' if i < 2 else 'B1'} for i, s in enumerate(allocations)}
            if configure: configure(raw)
        context = fixture.context(directory, plan, config_mutation=configuration)
        return plan, context, OSApplicationFactory().build(context)

    def waiting_shake(self, app, plan):
        app.client.start()
        identity = app.client.submit_run(RunRequest(plan, init_state(plan)))
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(identity)
        lifecycle.operations.dispatch_ready(identity)
        lifecycle.runs.advance_ready(identity)
        pending = app.client.execution.pending(identity)
        assert pending.prepared.runtime_step.op == 'agit'
        return identity, pending

    def compare_language(self, app, plan, result):
        assert result.ok, [d.to_dict() for d in result.diagnostics]
        baseline = run(plan, StubDriver(), init_state(plan))
        assert baseline.ok and result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
        assert not app.client.lifecycle.operations.resource.occupied()
        return result.user_result['os']['run_id']
