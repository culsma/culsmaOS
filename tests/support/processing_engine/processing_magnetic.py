"""Magnetic separation preserves typed fraction identity and run-owned field obligations."""

import ast
from pathlib import Path
import json
import subprocess
import sys
from dataclasses import replace
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


DECLARATIONS = '''let p=plate(format="96well",capacity=100uL); let w=p[A1]; let sample=w[0];
let stock=tube(capacity=2000uL,load=[content(kind=particulate,type=beads,code="BEADS",attrs={bead_property:magnetic}):10uL,content(kind=formulation,type=buffer,code="BUFFER"):80uL]);
let waste=tube(capacity=2000uL);
'''


MAGNETIC = '''with env(field=magnetic_rack) {
 hold(sample=sample);
 sep(sample=sample,program=magnetic_program(duration=5min));
 waste << [sample.contents[1]:40uL];
}'''


SOURCE = DECLARATIONS + 'sample << [stock];' + MAGNETIC


class MagneticFixture:
    def build(self, directory, source=SOURCE, configure=None):
        fixture = TransferMatrixFixture()
        plan = fixture.compile(source, directory)
        def configuration(raw):
            raw['modules'] = {'magnet':{'model':'magnetic module gen2','slot':'6','engage_height_mm':6,'aspirate_height_mm':2}}
            raw['labware']['assay'] = {'load_name':'nest_96_wellplate_100ul_pcr_full_skirt','module':'magnet'}
            allocations = [s for p in plan.plans for s in p.steps if s.op=='AllocContainer']
            raw['bindings'] = {}
            tube = 0
            for step in allocations:
                if 'carrier_position' in step.args:
                    address = {'labware':'assay','well':step.args['carrier_position']['value']}
                else:
                    tube += 1
                    address = {'labware':'tubes','well':f'A{tube}'}
                raw['bindings'][step.step_id] = address
            if configure: configure(raw)
        context = fixture.context(directory, plan, config_mutation=configuration)
        return plan, context, OSApplicationFactory().build(context)

    def waiting_separation(self, app, plan):
        app.client.start()
        identity = app.client.submit_run(RunRequest(plan,init_state(plan)))
        lifecycle=app.client.lifecycle
        lifecycle.runs.advance_ready(identity);lifecycle.operations.dispatch_ready(identity);lifecycle.runs.advance_ready(identity)
        pending=app.client.execution.pending(identity)
        assert pending.prepared.runtime_step.op=='sep'
        return identity,pending

    def compare(self, app, plan, result):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan,StubDriver(),init_state(plan))
        assert baseline.ok, baseline.diagnostics
        assert result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        identity=result.user_result['os']['run_id']
        assert app.client.lifecycle.reservations.get(identity).status=='released'
        assert not app.client.lifecycle.operations.resource.occupied()
        return identity
