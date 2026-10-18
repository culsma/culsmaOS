"""Unchanged full PCR and bead workflows share one fixed official OT-2 station."""
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
from .test_pcr_benchmark import PCRFixture
from .test_resident_protocols import ResidentProtocolHarness, ResidentProtocolFactory, DeviceFault

ROOT = Path(__file__).resolve().parents[1]
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


class TestMixedResidentProtocols:
    def test_complete_pcr_and_beads_share_one_fixed_station(self, tmp_path):
        probe = MixedProtocolFactory(gate_kind='PreparedTransfer')
        host = MixedProtocolHarness(tmp_path, probe).start()
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
            host.assert_tip_history(31)
            host.assert_idle(31)
            host.assert_protocol_commands()
            first_profile = host.checkpoint(first)['workspace']
            second_profile = host.checkpoint(second)['workspace']
            assert first_profile['bindings']['entry.s5::alloc'] == {'labware': 'pcr', 'well': 'A1'}
            assert second_profile['bindings']['entry.s5::alloc'] == {'labware': 'tubes', 'well': 'B2'}
            assert first_profile['plan_fingerprint'] != second_profile['plan_fingerprint']
            assert probe.dispatches[92]['available_tips'] == 90
            host.save_audit('mixed_complete_pcr_then_beads', [first, second])
        finally: host.stop()

    @pytest.mark.parametrize('fault', ['thermal', 'magnetic'])
    def test_unknown_batch_blocks_successors_across_restart(self, tmp_path, fault):
        probe = MixedProtocolFactory(gate_kind='PreparedTransfer', fault=fault)
        host = MixedProtocolHarness(tmp_path, probe).start()
        try:
            first = host.submit()['run_id']
            assert probe.entered.wait(5)
            second = host.submit(host.second_source)['run_id']
            third = host.submit()['run_id']
            probe.release.set()
            unknown = first if fault == 'thermal' else second
            assert host.settled(unknown)['status'] == 'needs_reconciliation'
            if fault == 'magnetic': host.assert_complete(first, host.first_source)
            else: host.assert_following_untouched(second)
            host.assert_following_untouched(third)
            assert {r['run_id'] for r in host.station()['resources']['station_reservations']} == {unknown}
            host.save_audit(f'mixed_{fault}_unknown_before_restart', [first, second, third])
            (tmp_path/'resident-protocol-audit.json').rename(tmp_path/'audit-before-restart.json')
        finally: host.stop()
        restarted = MixedProtocolHarness(tmp_path, MixedProtocolFactory())
        # Saved program/configuration snapshots, not source availability, own recovery.
        restarted.first_source.unlink(); restarted.second_source.unlink()
        restarted.start()
        try:
            restarted.wait(lambda: restarted.client.execute({'action':'host-status'})['blocked_run'] == unknown)
            assert restarted.status(unknown)['status'] == 'needs_reconciliation'
            restarted.assert_following_untouched(third)
            if fault == 'thermal': restarted.assert_following_untouched(second)
            restarted.client.execute({'action':'resume', 'run_id':unknown})
            restarted.wait(lambda: not restarted.status(unknown)['pending_controls'])
            assert restarted.status(unknown)['status'] == 'needs_reconciliation'
            assert not restarted.sessions.dispatches
            session = restarted.sessions.ports[0].session
            assert not session.backend.protocol.commands() and not session.backend.receipts
            assert not session.thermal.receipts and not session.magnetic.receipts
            expected = 6 if fault == 'thermal' else 15
            assert session.backend.available_tips() == 96 - expected
            tips = restarted.station()['devices'][0]['consumables']['tips']
            assert tips['known_consumed'] == expected and tips['available_from_records'] is None
            restarted.save_audit(f'mixed_{fault}_unknown_after_restart', [first, second, third])
        finally: restarted.stop()

    def test_cancel_pcr_at_boundary_allows_full_bead_protocol_after_cleanup(self, tmp_path):
        probe = MixedProtocolFactory(gate_kind='PreparedTemperatureHold')
        host = MixedProtocolHarness(tmp_path, probe).start()
        try:
            first = host.submit()['run_id']
            assert probe.entered.wait(10)
            second = host.submit(host.second_source)['run_id']
            host.client.execute({'action':'pause', 'run_id':first})
            probe.release.set()
            host.wait(lambda: host.status(first)['status'] == 'paused')
            host.assert_following_untouched(second)
            host.client.execute({'action':'cancel', 'run_id':first})
            assert host.settled(first)['status'] == 'cancelled'
            assert host.settled(second)['status'] == 'completed'
            host.assert_complete(second, host.second_source)
            assert host.status(first)['result']['os']['registered_material']['version'] == 2
            assert len(host.attempts(first)) == 2 and len(probe.ports[0].session.thermal.receipts) == 1
            owners = {a['attempt_id']:a['run_id'] for a in host.attempts()}
            assert [owners[d['attempt_id']] for d in probe.dispatches] == [first]*2 + [second]*12
            probe.ports[0].session.backend.thermocycler_access.require_inactive('cycler')
            host.assert_tip_history(31); host.assert_idle(31)
            host.save_audit('mixed_cancel_cleanup_then_beads', [first, second])
        finally: host.stop()

    def test_graceful_restart_continues_saved_program_without_repeating_prefix(self, tmp_path):
        probe = MixedProtocolFactory(gate_kind='PreparedTemperatureHold')
        host = MixedProtocolHarness(tmp_path, probe).start()
        try:
            first = host.submit()['run_id']
            assert probe.entered.wait(10)
            second = host.submit(host.second_source)['run_id']
            host.client.execute({'action':'pause', 'run_id':first}); probe.release.set()
            host.wait(lambda: host.status(first)['status'] == 'paused')
            host.assert_following_untouched(second)
            assert len(host.attempts(first)) == 2
            prefix_pickups = host.assert_tip_history(6)
            host.save_audit('mixed_paused_before_restart', [first, second])
            (tmp_path/'resident-protocol-audit.json').rename(tmp_path/'audit-before-restart.json')
        finally: host.stop()
        restarted = MixedProtocolHarness(tmp_path, MixedProtocolFactory())
        restarted.first_source.unlink(); restarted.second_source.unlink()
        restarted.start()
        try:
            session = restarted.sessions.ports[0].session
            assert not session.backend.protocol.commands()
            assert restarted.status(first)['status'] == 'paused'
            restarted.assert_following_untouched(second)
            assert session.backend.available_tips() == 90
            restarted.client.execute({'action':'resume','run_id':first})
            assert restarted.settled(second)['status'] == 'completed'
            restarted.assert_complete(first, restarted.first_source)
            restarted.assert_complete(second, restarted.second_source)
            assert len(session.thermal.receipts) == 91
            assert [(r.payload['request']['temperature_celsius'],r.payload['request']['duration_seconds'])
                for r in session.thermal.receipts] == PCRFixture().schedule()[1:]
            assert len(session.backend.receipts) == 6  # Only bead transfers in the new session.
            pickups = [c for c in session.backend.protocol.commands() if c.startswith('Picking up tip')]
            assert len(prefix_pickups + pickups) == len(set(prefix_pickups + pickups)) == 31
            restarted.assert_idle(31)
            assert session.backend.available_tips() == 65
            owners = {a['attempt_id']:a['run_id'] for a in restarted.attempts()}
            assert [owners[d['attempt_id']] for d in restarted.sessions.dispatches] == [first]*91 + [second]*12
            restarted.save_audit('mixed_graceful_restart_complete', [first, second])
        finally: restarted.stop()

    def test_incompatible_program_binding_rejects_without_poisoning_next_job(self, tmp_path):
        host = MixedProtocolHarness(tmp_path)
        raw = json.loads(host.catalog_path.read_text())
        raw['profiles'][0]['bindings']['entry.s0::alloc']['well'] = 'A6'
        host.catalog_path.write_text(json.dumps(raw)); host.start()
        try:
            first = host.submit()['run_id']
            second = host.submit(host.second_source)['run_id']
            assert host.settled(second)['status'] == 'completed'
            rejected = host.status(first)
            assert rejected['status'] == 'failed'
            assert rejected['result']['os']['preflight']['status'] == 'rejected'
            assert 'WORKSPACE_ADDRESS_UNCONFIGURED' in json.dumps(rejected)
            assert not host.attempts(first) and 'registered_material' not in rejected['result']['os']
            host.assert_complete(second, host.second_source)
            assert not host.sessions.ports[0].session.thermal.receipts
            host.assert_tip_history(25); host.assert_idle(25)
            host.save_audit('mixed_rejected_binding_then_beads', [first, second])
        finally: host.stop()

    def test_public_cli_runs_beads_then_pcr_in_one_resident_process(self, tmp_path):
        host = MixedProtocolHarness(tmp_path)
        serve = [sys.executable,'-m','culsma_os.cli','serve','--socket',str(host.endpoint),
            '--host-db',str(host.context.database_path),'--driver-config',str(host.context.config_path),
            '--workspace-config',str(host.catalog_path),'--artifacts-dir',str(tmp_path/'cli-artifacts')]
        commands = [serve]
        with (tmp_path/'resident-cli.log').open('w') as log:
            process = subprocess.Popen(serve, stdout=log, stderr=subprocess.STDOUT)
            try:
                host.wait(lambda: host.client.execute({'action':'host-status'})['status'] == 'ready', timeout=60)
                identities = []
                for source in (host.second_source, host.first_source):
                    command = [sys.executable,'-m','culsma_os.cli','submit',str(source),'--socket',str(host.endpoint)]
                    commands.append(command)
                    completed = subprocess.run(command,capture_output=True,text=True,timeout=30)
                    assert completed.returncode == 0, completed.stdout + completed.stderr
                    identities.append(json.loads(completed.stdout)['run_id'])
                beads, pcr = identities
                assert host.settled(pcr)['status'] == 'completed'
                host.assert_complete(beads, host.second_source)
                host.assert_complete(pcr, host.first_source)
                host.assert_idle(31)
                attempts = host.attempts()
                assert [a['run_id'] for a in attempts] == [beads]*12 + [pcr]*93
                assert process.poll() is None
                payload = {'scenario':'public_cli_beads_then_pcr','process_id':process.pid,
                    'commands':commands,'runs':[host.status(i) for i in identities],
                    'station':host.station(),'attempts':attempts}
                (tmp_path/'resident-cli-audit.json').write_text(json.dumps(payload,indent=2)+'\n')
                host.client.execute({'action':'shutdown'})
                assert process.wait(timeout=30) == 0
            finally:
                if process.poll() is None:
                    try: host.client.execute({'action':'shutdown'})
                    except (OSError,ValueError): process.terminate()
                    try: process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=10)
