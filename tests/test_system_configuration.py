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
from tests.test_transfer_matrix import TransferMatrixFixture, BUFFER
from tests.test_plate96 import PlateFixture


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


class TestSystemConfiguration:
    @pytest.mark.parametrize('pipette,mount,policy,flows', PROFILES)
    def test_same_program_profile_matrix(self, tmp_path, monkeypatch, pipette, mount, policy, flows, record_property):
        fixture = ConfigurationFixture()
        plan, context, app = fixture.build(tmp_path, pipette=pipette, mount=mount, policy=policy, flows=flows)
        try:
            backend = app.host.gateway.port.session.backend
            expected = (backend.pipette.flow_rate.aspirate, backend.pipette.flow_rate.dispense) if flows == 'default' else (3.0, 4.0)
            observations = fixture.watch_flow_rates(backend, monkeypatch)
            result = app.execute(plan, init_state(plan))
            fixture.assert_result(app, plan, result, (180, 20), 1)
            assert observations == [('aspirate', 20, expected[0]), ('dispense', 20, expected[1])]
            assert backend.protocol.loaded_instruments[mount] is backend.pipette
            assert backend.pipette.name == pipette
            raw = json.loads(context.config_path.read_text())
            receipt = backend.receipts[0]
            assert receipt.config_sha256 == DeckConfiguration.from_dict(raw).fingerprint()
            assert receipt.effective_config == DeckConfiguration.from_dict(raw).snapshot()
            assert receipt.instrument['aspirate_flow_rate_uL_s'] == expected[0]
            assert receipt.instrument['dispense_flow_rate_uL_s'] == expected[1]
            record_property('configuration_case', json.dumps({'profile': [pipette, mount, policy, flows], 'actual_flow_rates_uL_s': expected, 'config_sha256': receipt.config_sha256, 'outcome': 'completed'}))
        finally:
            app.close()

    @pytest.mark.parametrize('pipette,mount', list(product(PIPETTES, ('left', 'right'))))
    def test_group_uses_profile_and_relocated_deck(self, tmp_path, monkeypatch, pipette, mount, record_property):
        fixture = ConfigurationFixture()
        plan, context, app = fixture.build(tmp_path, GROUP_SOURCE, pipette, mount, flows='explicit', relocated=True)
        try:
            backend = app.host.gateway.port.session.backend
            observations = fixture.watch_flow_rates(backend, monkeypatch)
            result = app.execute(plan, init_state(plan))
            fixture.assert_result(app, plan, result, (40, *([20]*8)), 8)
            assert observations == [('aspirate', 20, 3.0), ('dispense', 20, 4.0)] * 8
            assert backend.protocol.loaded_instruments[mount] is backend.pipette
            assert backend.protocol.loaded_labwares[7] is backend.labware['tubes']
            assert backend.protocol.loaded_labwares[9] is backend.labware['plate1']
            assert backend.protocol.loaded_labwares[8].is_tiprack
            assert len({r.config_sha256 for r in backend.receipts}) == 1
            data = app.client.execution.host.codec.loads(app.client.get_run(result.user_result['os']['run_id']).checkpoint)
            assert len(data['confirmed']) == 1 and len(data['confirmed'][0].resolution.members) == 8
            record_property('configuration_case', json.dumps({'group': True, 'profile': [pipette, mount], 'slots': [7, 8, 9], 'members': 8, 'outcome': 'completed'}))
        finally:
            app.close()

    @pytest.mark.parametrize('pipette,policy,expected', [
        ('p20_single_gen2', 'single', None),
        ('p20_single_gen2', 'balanced_split', (15, 15, 15)),
        ('p300_single_gen2', 'single', (45,)),
        ('p300_single_gen2', 'balanced_split', (45,)),
    ])
    def test_same_quantity_has_profile_owned_strokes(self, tmp_path, pipette, policy, expected, record_property):
        fixture = ConfigurationFixture()
        source = SOURCE.replace('source:20uL', 'source:45uL')
        plan, context, app = fixture.build(tmp_path, source, pipette, policy=policy)
        try:
            backend = app.host.gateway.port.session.backend
            result = app.execute(plan, init_state(plan))
            if expected is None:
                assert not result.ok and result.user_result['os']['status'] == 'failed'
                assert 'DRV_OT_VOLUME_RANGE' in ' '.join(d.message for d in result.diagnostics)
                assert not backend.protocol.commands()
                assert backend.available_tips() == 96
                assert [c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values()] == [200, 0]
            else:
                fixture.assert_result(app, plan, result, (155, 45), len(expected))
                assert [c.volume_uL for r in backend.receipts for c in r.operation.commands] == pytest.approx(expected)
            record_property('configuration_case', json.dumps({'quantity_uL': 45, 'profile': [pipette, policy], 'strokes_uL': expected, 'outcome': 'rejected' if expected is None else 'completed'}))
        finally:
            app.close()

    @pytest.mark.parametrize('field', ['configuration_revision', 'calibration_revision'])
    @pytest.mark.parametrize('source', [SOURCE, GROUP_SOURCE], ids=['scalar', 'group'])
    def test_revision_changed_after_preparation_rejects_before_intent(self, tmp_path, monkeypatch, field, source):
        fixture = ConfigurationFixture()
        plan, context, app = fixture.build(tmp_path, source)
        try:
            transfer = app.client.lifecycle.operations.transfer
            method = 'prepare_group' if source == GROUP_SOURCE else 'prepare'
            original = getattr(transfer, method)
            prepared = []
            def changed(request):
                value = original(request)
                prepared.append(value)
                fixture.change_revision(app, field)
                return value
            monkeypatch.setattr(transfer, method, changed)
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result['os']['status'] == 'failed'
            assert 'DEVICE_CONFIGURATION_STALE' in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert app.client.lifecycle.evidence.find_attempt(prepared[0].effect_id) is None
            assert not app.client.lifecycle.operations.resource.occupied()
        finally:
            app.close()

    @pytest.mark.parametrize('field', ['configuration_revision', 'calibration_revision'])
    def test_revision_change_inside_group_preserves_prefix(self, tmp_path, monkeypatch, field):
        fixture = ConfigurationFixture()
        plan, context, app = fixture.build(tmp_path, GROUP_SOURCE)
        try:
            gateway = app.host.gateway
            original = gateway.execute_group_member
            def change_after_member(*args):
                receipt = original(*args)
                fixture.change_revision(app, field)
                return receipt
            monkeypatch.setattr(gateway, 'execute_group_member', change_after_member)
            result = app.execute(plan, init_state(plan))
            run_id = result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status'] == 'needs_reconciliation'
            assert len(gateway.port.session.backend.receipts) == 1
            assert gateway.port.session.backend.available_tips() == 95
            state = app.host.material.get(run_id)[1]
            assert [c['volume_uL'] for c in state['containers'].values()] == [180, 20, *([0]*7)]
            assert app.client.lifecycle.operations.resource.occupied()
            before = list(gateway.port.session.backend.protocol.commands())
            assert app.client.run_until_settled(run_id).status == 'needs_reconciliation'
            assert gateway.port.session.backend.protocol.commands() == before
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            owner = restarted.client.lifecycle.reservations.get(run_id)
            registered = restarted.client.lifecycle.device.get('opentrons')
            assert getattr(registered, field).endswith('-changed')
            with pytest.raises(ValueError, match='DEVICE_SESSION_CONFIGURATION_MISMATCH'):
                restarted.client.take_over_run(run_id)
            assert restarted.client.lifecycle.reservations.get(run_id) == owner
            assert restarted.client.lifecycle.device.get('opentrons') == registered
            restarted.client.start()
            assert restarted.client.get_run(run_id).status == 'needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.host.gateway.port.session.backend.available_tips() == 95
            assert restarted.client.lifecycle.operations.resource.occupied()
        finally:
            restarted.close()

    def test_file_change_only_applies_to_new_session(self, tmp_path):
        fixture = ConfigurationFixture()
        plan, context, app = fixture.build(tmp_path)
        raw = json.loads(context.config_path.read_text())
        original_revision = DeckConfiguration.from_dict(raw).fingerprint()
        raw['mount'] = 'left'
        raw['transfer_policy']['aspirate_flow_rate_uL_s'] = 7.0
        raw['transfer_policy']['dispense_flow_rate_uL_s'] = 9.0
        context.config_path.write_text(json.dumps(raw))
        try:
            fixture.assert_result(app, plan, app.execute(plan, init_state(plan)), (180, 20), 1)
            receipt = app.host.gateway.port.session.backend.receipts[0]
            assert receipt.config_sha256 == original_revision
            assert receipt.instrument['aspirate_flow_rate_uL_s'] == 3.0
            assert receipt.effective_config['mount'] == 'right'
        finally:
            app.close()
        other = OSApplicationFactory().build(replace(context, database_path=tmp_path/'new-session.sqlite3', artifacts_dir=tmp_path/'new-artifacts'))
        try:
            fixture.assert_result(other, plan, other.execute(plan, init_state(plan)), (180, 20), 1, previous_tips=1)
            receipt = other.host.gateway.port.session.backend.receipts[0]
            assert receipt.config_sha256 != original_revision
            assert receipt.config_sha256 == DeckConfiguration.from_dict(raw).fingerprint()
            assert receipt.instrument['aspirate_flow_rate_uL_s'] == 7.0
            assert receipt.instrument['dispense_flow_rate_uL_s'] == 9.0
            assert receipt.effective_config['mount'] == 'left'
        finally:
            other.close()


    @pytest.mark.parametrize('pipette,policy,count', [
        ('p20_single_gen2', 'single', None),
        ('p20_single_gen2', 'balanced_split', 24),
        ('p300_single_gen2', 'single', 8),
        ('p300_single_gen2', 'balanced_split', 8),
    ])
    def test_group_stroke_policy_admits_whole_budget(self, tmp_path, pipette, policy, count):
        fixture = ConfigurationFixture()
        source = GROUP_SOURCE.replace(':200uL]);', ':1000uL]);').replace('stock:20uL', 'stock:45uL')
        plan, context, app = fixture.build(tmp_path, source, pipette, policy=policy)
        try:
            result = app.execute(plan, init_state(plan))
            backend = app.host.gateway.port.session.backend
            if count is None:
                assert not result.ok and result.user_result['os']['status'] == 'failed'
                assert not backend.protocol.commands()
                assert backend.available_tips() == 96
                assert not app.client.lifecycle.operations.resource.occupied()
            else:
                fixture.assert_result(app, plan, result, (640, *([45]*8)), count)
                assert len(backend.receipts) == 8
                expected = [15]*24 if count == 24 else [45]*8
                assert [c.volume_uL for r in backend.receipts for c in r.operation.commands] == pytest.approx(expected)
                assert app.client.lifecycle.evidence.known_consumption(app.client.lifecycle.device_id) == {'tips': count}
        finally:
            app.close()

    @pytest.mark.parametrize('entry', ['language', 'os'])
    def test_cli_applies_external_configuration(self, tmp_path, entry):
        fixture = ConfigurationFixture()
        source = SOURCE.replace('source:20uL', 'source:45uL')
        plan, context, app = fixture.build(tmp_path, source, mount='left', policy='balanced_split')
        app.close()
        artifacts = tmp_path/'cli-artifacts'
        command = [str(Path(sys.executable).parent/'culsma')] if entry == 'language' else [sys.executable, '-m', 'culsma_os.cli']
        completed = subprocess.run([*command, 'run', str(tmp_path/'protocol.culs'), '--driver', 'opentrons-simulator', '--driver-config', str(context.config_path), '--artifacts-dir', str(artifacts)], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stdout+completed.stderr
        report = json.loads((artifacts/'run.json').read_text())
        assert report['user_result']['os']['status'] == 'completed'
        receipts = [e['payload']['driver_payload'] for e in report['events'] if e['payload'].get('driver_code') == 'OS_MATERIAL_REGISTERED']
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt['effective_config']['mount'] == 'left'
        assert receipt['instrument']['aspirate_flow_rate_uL_s'] == 3.0
        assert receipt['instrument']['dispense_flow_rate_uL_s'] == 4.0
        assert [t['volume_uL'] for t in receipt['transfers']] == [15, 15, 15]
        assert receipt['config_sha256'] == DeckConfiguration.from_dict(json.loads(context.config_path.read_text())).fingerprint()
