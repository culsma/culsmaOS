"""Complete protocols share a live station while retaining run-owned semantics."""

from tests.support.paths import ROOT
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma_os.bootstrap import OpentronsSessionFactory
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.codec import RuntimeCheckpointCodecInteractor
from tests.support.integration.resident_docking import ResidentDockingHarness, ObservedMotionFactory, ObservedMotionPort, DeviceFault


EXAMPLE = ROOT / 'examples/magnetic-buffer-exchange'


class ResidentProtocolFactory(ObservedMotionFactory):
    def __init__(self, gate_kind=None, unknown_second=False):
        super().__init__(gate_kind)
        self.unknown_second = unknown_second

    def build(self, context):
        delegate, *description = OpentronsSessionFactory().build(context)
        session = delegate.session
        self.initial.append({'positions': session.motion.positions() if session.motion else None,
                             'commands': tuple(session.backend.protocol.commands())})
        port = ObservedMotionPort(delegate, self)
        self.ports.append(port)
        if self.unknown_second:
            protocol = port.session.backend.protocol
            # First complete protocol makes six moves. Lose the second program's
            # first removal response after the official API actually returns.
            protocol.move_labware = DeviceFault(protocol.move_labware, hit=8, after=True)
        return port, *description


class ResidentProtocolHarness(ResidentDockingHarness):
    def __init__(self, directory, profile='flex', sessions=None):
        super().__init__(directory, sessions or ResidentProtocolFactory())
        self.profile = profile
        self.context = replace(self.context, config_path=EXAMPLE / (
            'deck-flex.json' if profile == 'flex' else 'deck.json'))
        self.settings = ResidentHostSettings(self.context, self.endpoint, 0.01)
        self.first_source.write_bytes((EXAMPLE / 'protocol.culs').read_bytes())
        self.second_source.write_text(self.first_source.read_text().replace(
            'wash_buffer:80uL', 'wash_buffer:60uL'))
        self.references = {}
        for source in (self.first_source, self.second_source):
            compiled = CompilationInteractor().compile([source])
            baseline = run(compiled.plan, StubDriver(), compiled.state)
            assert baseline.ok, baseline.diagnostics
            self.references[source] = baseline.state.artifacts

    def require_ready(self):
        status = self.client.execute({'action': 'host-status'})
        assert status['status'] != 'failed', status
        return status['status'] == 'ready'

    def start(self, expect='ready'):
        self.thread.start()
        try:
            self.wait(self.require_ready, timeout=60)
        except BaseException:
            self.stop()
            raise
        return self

    def checkpoint(self, run_id):
        with sqlite3.connect(f'file:{self.context.database_path}?mode=ro', uri=True) as connection:
            saved, = connection.execute('SELECT checkpoint FROM os_runs WHERE run_id=?', (run_id,)).fetchone()
        return RuntimeCheckpointCodecInteractor().loads(saved)

    def settled(self, run_id):
        self.wait(lambda: self.status(run_id)['status'] in {
            'completed', 'failed', 'cancelled', 'needs_reconciliation'}, timeout=90)
        return self.status(run_id)

    def assert_complete(self, run_id, source):
        status = self.status(run_id)
        assert status['status'] == 'completed', status
        os = status['result']['os']
        assert os['registered_material']['version'] == 9
        assert os['registered_material']['state'] == self.references[source]['material_state']
        assert self.checkpoint(run_id)['state'].artifacts['protocol_outputs'] == self.references[source]['protocol_outputs']
        assert len(self.attempts(run_id)) == (18 if self.profile == 'flex' else 12)
        return os

    def station(self):
        return self.client.execute({'action': 'device-status'})

    def assert_idle(self, consumed, revision=None):
        report = self.station()
        assert not report['devices'][0]['unresolved_operations']
        tips = report['devices'][0]['consumables']['tips']
        assert tips['known_consumed'] == consumed
        assert tips['available_from_records'] == 96 - consumed
        assert tips['status'] == 'recorded'
        for key in ('permits', 'locks', 'station_reservations', 'station_locks'):
            assert not report['resources'][key], report['resources']
        assert not self.rows('os_resource_locks')
        if revision is not None:
            positions = report['devices'][0]['positions']
            assert positions['current']['assay'] == 'D1'
            assert positions['revision'] == revision
            assert not self.rows('os_station_motion_intents')
        return report

    def assert_tip_history(self, consumed):
        backend = self.sessions.ports[0].session.backend
        pickups = [c for c in backend.protocol.commands() if c.startswith('Picking up tip')]
        assert len(pickups) == len(set(pickups)) == consumed
        assert backend.available_tips() == 96 - consumed
        return pickups

    def assert_fifo(self, run_ids):
        attempts = self.attempts()
        owners = {a['attempt_id']: a['run_id'] for a in attempts}
        per_run = 18 if self.profile == 'flex' else 12
        assert [owners[d['attempt_id']] for d in self.sessions.dispatches] == [
            run_id for run_id in run_ids for _ in range(per_run)]
        assert all(d['thread'] == 'culsma-os-execution' for d in self.sessions.dispatches)
        assert len(self.sessions.ports) == 1

    def save_audit(self, scenario, run_ids):
        payload = {'scenario': scenario, 'profile': self.profile,
            'session_count': len(self.sessions.ports),
            'runs': [self.status(run_id) for run_id in run_ids],
            'station': self.station(), 'attempts': self.attempts(),
            'dispatches': self.sessions.dispatches,
            'official_commands': list(self.sessions.ports[0].session.backend.protocol.commands())}
        path = self.first_source.parent / 'resident-protocol-audit.json'
        path.write_text(json.dumps(payload, indent=2) + '\n')
        return payload
