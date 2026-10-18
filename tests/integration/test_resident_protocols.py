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
from tests.support.integration.resident_protocols import ROOT, EXAMPLE, ResidentProtocolFactory, ResidentProtocolHarness


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

