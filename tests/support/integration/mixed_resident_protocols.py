"""Unchanged full PCR and bead workflows share one fixed official OT-2 station."""

from tests.support.paths import ROOT
from dataclasses import replace
import json
import subprocess
import sys
from pathlib import Path
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from tests.support.integration.pcr_benchmark import PCRFixture
from tests.support.integration.resident_protocols import ResidentProtocolHarness, ResidentProtocolFactory, DeviceFault


EXAMPLE = ROOT/'examples/resident-station'


class MixedProtocolFactory(ResidentProtocolFactory):
    def __init__(self, gate_kind=None, fault=None):
        super().__init__(gate_kind)
        self.fault = fault

    def build(self, context):
        port, *description = super().build(context)
        if self.fault == 'thermal':
            module = port.session.backend.modules['cycler']
            module.set_block_temperature = DeviceFault(module.set_block_temperature, hit=1, after=True)
        elif self.fault == 'magnetic':
            module = port.session.backend.modules['magnet']
            module.disengage = DeviceFault(module.disengage, hit=1, after=True)
        return port, *description


class MixedProtocolHarness(ResidentProtocolHarness):
    def __init__(self, directory, sessions=None):
        super().__init__(directory, 'ot2', sessions or MixedProtocolFactory())
        self.first_source.write_bytes((ROOT/'examples/pcr-benchmark/protocol.culs').read_bytes())
        self.second_source.write_bytes((ROOT/'examples/magnetic-buffer-exchange/protocol.culs').read_bytes())
        catalog = json.loads((EXAMPLE/'workspaces.json').read_text())
        for profile, source in zip(catalog['profiles'], (self.first_source, self.second_source)):
            profile['program'] = source.name
        self.catalog_path = directory/'workspaces.json'
        self.catalog_path.write_text(json.dumps(catalog))
        self.context = replace(self.context, config_path=EXAMPLE/'deck.json', workspace_config_path=self.catalog_path)
        self.settings = ResidentHostSettings(self.context, self.endpoint, 0.01)
        self.references = {}
        for source in (self.first_source, self.second_source):
            compiled = CompilationInteractor().compile([source])
            baseline = run(compiled.plan, StubDriver(), compiled.state)
            assert baseline.ok
            self.references[source] = baseline.state.artifacts

    def settled(self, run_id):
        self.wait(lambda: self.status(run_id)['status'] in {
            'completed', 'failed', 'cancelled', 'needs_reconciliation'}, timeout=240)
        return self.status(run_id)

    def assert_complete(self, run_id, source):
        status = self.status(run_id)
        assert status['status'] == 'completed', status
        expected = 93 if source == self.first_source else 9
        registered = status['result']['os']['registered_material']
        assert registered['version'] == expected
        assert registered['state'] == self.references[source]['material_state']
        data = self.checkpoint(run_id)
        assert data['schema'] == 4
        assert data['state'].artifacts['protocol_outputs'] == self.references[source]['protocol_outputs']
        assert len(self.attempts(run_id)) == (93 if source == self.first_source else 12)
        assert data['workspace']['id'] == ('pcr' if source == self.first_source else 'beads')
        return status

    def assert_fifo(self, run_ids):
        owners = {a['attempt_id']: a['run_id'] for a in self.attempts()}
        expected = [run_ids[0]]*93 + [run_ids[1]]*12
        assert [owners[d['attempt_id']] for d in self.sessions.dispatches] == expected
        assert len(self.sessions.ports) == 1
        assert all(d['thread'] == 'culsma-os-execution' for d in self.sessions.dispatches)

    def assert_protocol_commands(self):
        session = self.sessions.ports[0].session
        assert [(r.payload['request']['temperature_celsius'], r.payload['request']['duration_seconds'])
            for r in session.thermal.receipts] == PCRFixture().schedule()
        assert [r.payload['operation_kind'] for r in session.magnetic.receipts] == [
            'magnetic_separation', 'magnetic_release']*3
        assert [len(r.operation.commands) for r in session.backend.receipts] == [6, 5, 4, 4, 4, 4, 4]
        session.backend.thermocycler_access.require_inactive('cycler')
        assert not session.magnetic.held
        assert set(session.backend.modules) == {'cycler', 'magnet'}
        assert session.backend.labware['pcr'].parent is session.backend.modules['cycler']
        assert session.backend.labware['beads'].parent is session.backend.modules['magnet']
