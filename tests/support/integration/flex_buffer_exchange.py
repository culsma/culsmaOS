"""The same wash protocol on a passive block, with journaled field-removal moves."""

from tests.support.paths import ROOT
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.workspace_manager.magnetic_block import BlockFixture
from tests.support.integration.flex_workstation import WorkstationDeviceFault


EXAMPLE=ROOT/'examples/magnetic-buffer-exchange'


class FlexBufferExchangeFixture:
    def build(self, directory, change=None):
        def configure(raw, plan):
            raw['labware_moves']={s.step_id:[{'labware':'assay','destination':'module:magnet'}]
                for protocol in plan.plans for s in protocol.steps if s.op=='sep'}
            if change is not None: change(raw, plan)
        return BlockFixture().build(directory, (EXAMPLE/'protocol.culs').read_text(), configure)

    def complete(self, app, plan, result):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan, StubDriver(), init_state(plan)); assert baseline.ok
        assert result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs']==baseline.state.artifacts['protocol_outputs']
        identity=result.user_result['os']['run_id']; session=app.host.gateway.port.session
        assert [c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values()]==[10,0,240,240]
        assert app.host.material.get(identity)[2]==9
        assert len(app.client.lifecycle.evidence.attempts_for_run(identity))==18
        assert session.motion.positions()['assay']=='D1' and session.motion.state['revision']==6
        assert not session.magnetic.held and session.backend.available_tips()==90
        assert app.client.lifecycle.reservations.get(identity).status=='released'
        assert not app.client.lifecycle.operations.resource.occupied()
        assert not app.client.lifecycle.operations.motions.motion.repository.pending('opentrons')
        return identity
