"""Complete static bead-buffer exchange, with repeated condition ownership."""

from tests.support.paths import ROOT
from pathlib import Path
import json,subprocess,sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.processing_engine.processing_magnetic import MagneticFixture
from tests.support.integration.flex_workstation import WorkstationDeviceFault


EXAMPLE=ROOT/'examples/magnetic-buffer-exchange'


class BufferExchangeFixture:
    def build(self,directory):
        return MagneticFixture().build(directory,(EXAMPLE/'protocol.culs').read_text())

    def complete(self,app,plan,result):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan,StubDriver(),init_state(plan));assert baseline.ok
        assert result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs']==baseline.state.artifacts['protocol_outputs']
        identity=result.user_result['os']['run_id'];session=app.host.gateway.port.session
        containers=result.state.artifacts['material_state']['containers']
        assert [c['volume_uL'] for c in containers.values()]==[10,0,240,240]
        waste=list(containers.values())[-1]
        assert waste['components']=={'BEADS':0,'STORAGE_BUFFER':80,'WASH_BUFFER':160}
        assert app.host.material.get(identity)[2]==9
        assert len(app.client.lifecycle.evidence.attempts_for_run(identity))==12
        assert app.client.lifecycle.reservations.get(identity).status=='released'
        assert not app.client.lifecycle.operations.resource.occupied()
        assert not session.magnetic.held
        assert session.backend.available_tips()==90
        return identity
