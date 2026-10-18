"""Same language intent across explicit system profiles and revision boundaries."""

from dataclasses import replace
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_opentrons.config import DeckConfiguration
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER
from tests.support.transfer_engine.plate96 import PlateFixture


PIPETTES = ('p20_single_gen2', 'p300_single_gen2')


PROFILES = list(product(PIPETTES, ('left', 'right'), ('single', 'balanced_split'), ('default', 'explicit')))


SOURCE = f'let source=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let target=tube(capacity=2000uL); target << [source:20uL];'


GROUP_SOURCE = f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let assay=plate(format="96well",capacity=200uL); assay[A1:H1] << [stock:20uL];'


class ConfigurationFixture:
    def build(self, directory, source=SOURCE, pipette='p20_single_gen2', mount='right', policy='single', flows='explicit', relocated=False):
        fixture = PlateFixture() if 'plate(' in source else TransferMatrixFixture()
        plan = fixture.compile(source, directory)
        def configure(raw):
            raw['mount'] = mount
            if flows == 'explicit':
                raw['transfer_policy'].update(aspirate_flow_rate_uL_s=3.0, dispense_flow_rate_uL_s=4.0)
            if relocated:
                raw['tiprack']['slot'] = '8'
                raw['labware']['tubes']['slot'] = '7'
                if 'plate1' in raw['labware']:
                    raw['labware']['plate1']['slot'] = '9'
        context = fixture.context(directory, plan, pipette, policy, configure)
        return plan, context, OSApplicationFactory().build(context)

    def watch_flow_rates(self, backend, monkeypatch):
        observed = []
        for name in ('aspirate', 'dispense'):
            original = getattr(backend.pipette, name)
            def record(volume, location, action=name, call=original):
                observed.append((action, volume, getattr(backend.pipette.flow_rate, action)))
                return call(volume, location)
            monkeypatch.setattr(backend.pipette, name, record)
        return observed

    def assert_result(self, app, plan, result, volumes, count, previous_tips=0):
        assert result.ok, [d.to_dict() for d in result.diagnostics]
        assert result.user_result['os']['status'] == 'completed'
        assert result.state.artifacts['material_state'] == run(plan, StubDriver()).state.artifacts['material_state']
        actual = [c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values()]
        assert actual == pytest.approx(volumes)
        backend = app.host.gateway.port.session.backend
        assert sum(len(r.operation.commands) for r in backend.receipts) == count
        assert backend.available_tips() == 96-count-previous_tips
        assert not app.client.lifecycle.operations.resource.occupied()

    def change_revision(self, app, field):
        device = app.client.lifecycle.device
        snapshot = device.get(app.client.lifecycle.device_id)
        device.register(replace(snapshot, **{field: getattr(snapshot, field) + '-changed'}))
