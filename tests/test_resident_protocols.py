"""Complete protocols share a live station while retaining run-owned semantics."""
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
from .test_resident_docking import ResidentDockingHarness, ObservedMotionFactory, ObservedMotionPort, DeviceFault

ROOT = Path(__file__).resolve().parents[1]
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


class TestResidentProtocols:
    @pytest.mark.parametrize('profile', ['ot2', 'flex'])
    def test_complete_protocols_share_station_without_sharing_program_state(self, tmp_path, profile):
        probe = ResidentProtocolFactory(gate_kind='PreparedTransfer')
        host = ResidentProtocolHarness(tmp_path, profile, probe).start()
        try:
            first = host.submit()['run_id']
            assert probe.entered.wait(5)
            second = host.submit(host.second_source)['run_id']
            host.assert_following_untouched(second)
            probe.release.set()
            assert host.settled(second)['status'] == 'completed'
            host.assert_complete(first, host.first_source)
            host.assert_complete(second, host.second_source)
            host.assert_fifo([first, second])
            host.assert_tip_history(12)
            host.assert_idle(12, 12 if profile == 'flex' else None)
            assert probe.dispatches[(18 if profile == 'flex' else 12) - 1]['available_tips'] == 90
            assert not probe.ports[0].session.magnetic.held
            host.save_audit('two_complete_protocols', [first, second])
        finally:
            host.stop()
        assert probe.ports[0].session.closed

    def test_exhausted_rack_is_not_reset_by_the_next_program(self, tmp_path):
        host = ResidentProtocolHarness(tmp_path).start()
        identities = []
        try:
            # No mocked counter: exhaust all 96 tips through sixteen real virtual
            # protocols, then submit another full protocol to the same endpoint.
            for _ in range(16):
                identity = host.submit()['run_id']
                identities.append(identity)
                assert host.settled(identity)['status'] == 'completed'
                host.assert_complete(identity, host.first_source)
            host.assert_fifo(identities)
            host.assert_tip_history(96)
            host.assert_idle(96, 96)
            before = len(host.sessions.dispatches)
            rejected = host.submit()['run_id']
            identities.append(rejected)
            status = host.settled(rejected)
            assert status['status'] == 'failed', status
            assert 'INSUFFICIENT' in json.dumps(status)
            assert len(host.sessions.dispatches) == before
            assert not host.attempts(rejected)
            assert 'registered_material' not in status['result']['os']
            host.assert_tip_history(96)
            host.assert_idle(96, 96)
            assert len(host.sessions.ports) == 1
            host.save_audit('rack_exhaustion', identities)
        finally:
            host.stop()

    def test_unknown_second_protocol_retains_station_and_blocks_third(self, tmp_path):
        probe = ResidentProtocolFactory(gate_kind='PreparedTransfer', unknown_second=True)
        host = ResidentProtocolHarness(tmp_path, sessions=probe).start()
        try:
            first = host.submit()['run_id']
            assert probe.entered.wait(5)
            second = host.submit(host.second_source)['run_id']
            third = host.submit()['run_id']
            probe.release.set()
            assert host.settled(second)['status'] == 'needs_reconciliation'
            host.assert_complete(first, host.first_source)
            host.assert_following_untouched(third)
            report = host.station()
            assert host.client.execute({'action': 'host-status'})['blocked_run'] == second
            assert {r['run_id'] for r in report['resources']['station_reservations']} == {second}
            assert report['devices'][0]['positions']['current'] is None
            assert report['devices'][0]['consumables']['tips']['available_from_records'] is None
            assert host.rows('os_station_motion_intents')
            attempts = {a['attempt_id']: a['run_id'] for a in host.attempts()}
            owners = [attempts[d['attempt_id']] for d in probe.dispatches]
            assert owners[:18] == [first] * 18 and set(owners[18:]) == {second}
            count = len(probe.dispatches)
            # Service remains responsive, without dispatching the queued successor.
            for _ in range(3):
                assert host.client.execute({'action': 'host-status'})['blocked_run'] == second
                host.assert_following_untouched(third)
            assert len(probe.dispatches) == count and len(probe.ports) == 1
            host.save_audit('unknown_second_blocks_third', [first, second, third])
        finally:
            host.stop()

    def test_cancel_finalizes_field_before_the_next_complete_protocol(self, tmp_path):
        probe = ResidentProtocolFactory(gate_kind='PreparedLabwareMove')
        host = ResidentProtocolHarness(tmp_path, sessions=probe).start()
        try:
            first = host.submit()['run_id']
            assert probe.entered.wait(5)
            second = host.submit(host.second_source)['run_id']
            host.client.execute({'action': 'pause', 'run_id': first})
            probe.release.set()
            host.wait(lambda: host.status(first)['status'] == 'paused')
            host.assert_following_untouched(second)
            positions = host.station()['devices'][0]['positions']
            assert positions['current']['assay'] == 'module:magnet' and positions['revision'] == 1
            host.client.execute({'action': 'cancel', 'run_id': first})
            assert host.settled(first)['status'] == 'cancelled'
            assert host.settled(second)['status'] == 'completed'
            host.assert_complete(second, host.second_source)
            assert host.status(first)['result']['os']['registered_material']['version'] == 2
            first_attempts = host.attempts(first)
            assert [a['context']['description'].get('operation_kind', 'transfer') for a in first_attempts] == [
                'transfer', 'labware_move', 'magnetic_separation', 'labware_move', 'magnetic_release']
            owners = {a['attempt_id']: a['run_id'] for a in host.attempts()}
            assert [owners[d['attempt_id']] for d in probe.dispatches] == [first] * 5 + [second] * 18
            assert len(probe.ports) == 1
            # Cancellation records removal and release at revision 2, then the
            # next full protocol adds six moves. It never resets placement.
            assert len(probe.ports[0].session.motion.receipts) == 8
            host.assert_tip_history(7)
            host.assert_idle(7, 8)
            assert not probe.ports[0].session.magnetic.held
            host.save_audit('cancel_cleanup_precedes_successor', [first, second])
        finally:
            host.stop()
