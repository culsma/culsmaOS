from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.processing_engine.processing_thermal import ThermalFixture, DECLARATIONS, SOURCE
from culsma_os.processing_engine.interactors.material_volume import ProcessingMaterialVolumeInteractor
from culsma_os.driver_framework.models import OperationPreparationRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
from tests.support.processing_engine.processing_thermocycler import SCALAR_SOURCE, HOLDS, CYCLE_SOURCE, ThermocyclerFixture


class TestThermocyclerProcessing:
    def test_transfer_holds_transfer(self, tmp_path):
        plan, context, app = ThermocyclerFixture().build(tmp_path, CYCLE_SOURCE)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [diagnostic.to_dict() for diagnostic in result.diagnostics]
            assert result.user_result['os']['status'] == 'completed'
            baseline = run(plan, StubDriver(), init_state(plan))
            assert baseline.ok
            assert result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
            assert TransferMatrixFixture().volumes(result) == (170, 30)
            session = app.host.gateway.port.session
            assert len(session.backend.receipts) == 2 and len(session.thermal.receipts) == 3
            assert [(r.payload['request']['temperature_celsius'], r.payload['request']['duration_seconds'])
                    for r in session.thermal.receipts] == [(95, 1), (60, 2), (72, 3)]
            assert all(r.outcome == 'completed' and not r.payload['sample_temperature_measured'] for r in session.thermal.receipts)
            assert [r.payload['block_max_volume_uL'] for r in session.thermal.receipts] == [50, 50, 50]
            commands = session.backend.protocol.commands()
            assert len(commands) == 22
            assert 'Opening Thermocycler lid' == commands[0]
            assert 'Aspirating 50' in commands[2]
            assert '95.0' in commands[6] and '60.0' in commands[10] and '72.0' in commands[14]
            assert 'Aspirating 20' in commands[19]
            identity = result.user_result['os']['run_id']
            assert app.host.material.get(identity)[2] == 5
            assert app.client.lifecycle.reservations.get(identity).status == 'released'
            assert not app.client.lifecycle.operations.resource.occupied()
            assert session.backend.available_tips() == 94
        finally:
            app.close()

    @pytest.mark.parametrize('kind', ['fractional', 'range', 'collateral'])
    def test_rejects_before_module_commands(self, tmp_path, kind):
        source = DECLARATIONS + 'with env(thermal=37C,duration=1s) { hold(w[0]); }'
        if kind == 'fractional': source = source.replace('37C', '37.5C')
        if kind == 'range': source = source.replace('37C', '100C')
        if kind == 'collateral': source = source.replace('with env', 'let extra=p[B1]; with env')
        plan, context, app = ThermocyclerFixture().build(tmp_path, source)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result['os']['status'] == 'failed'
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert not app.host.gateway.port.session.thermal.receipts
            assert not app.client.lifecycle.operations.resource.occupied()
        finally:
            app.close()

    def test_unknown_hold_retains_isolation(self, tmp_path, monkeypatch):
        plan, context, app = ThermocyclerFixture().build(tmp_path)
        session = app.host.gateway.port.session
        original = session.backend.modules['cycler'].set_block_temperature
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('lost blocking hold acknowledgment')
        monkeypatch.setattr(session.backend.modules['cycler'], 'set_block_temperature', fail)
        try:
            result = app.execute(plan, init_state(plan))
            identity = result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status'] == 'needs_reconciliation'
            assert len(session.backend.receipts) == 1 and session.thermal.receipts[0].outcome == 'unknown'
            assert TransferMatrixFixture().volumes(result) == (150, 50)
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.reservations.get(identity).status == 'active'
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally:
            restarted.close()

    def test_saved_receipt_recovers_without_reheating(self, tmp_path, monkeypatch):
        plan, context, app = ThermocyclerFixture().build(tmp_path)
        identity, pending = ThermalFixture().waiting_hold(app, plan)
        operations = app.client.lifecycle.operations
        def crash(*args, **kwargs): raise KeyboardInterrupt('after durable thermocycler receipt')
        monkeypatch.setattr(operations.material, 'reconcile', crash)
        try:
            with pytest.raises(KeyboardInterrupt): operations.dispatch_ready(identity)
            assert operations.evidence.find_evidence(pending.effect_id).outcome == 'completed'
            assert len(app.host.gateway.port.session.thermal.receipts) == 1
        finally:
            app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'completed'
            session = restarted.host.gateway.port.session
            assert not session.thermal.receipts and len(session.backend.receipts) == 1
            assert not any('well block temperature' in command for command in session.backend.protocol.commands())
            assert TransferMatrixFixture().volumes(restarted.host.result(identity)) == (170, 30)
            assert restarted.host.material.get(identity)[2] == 3
        finally:
            restarted.close()

    @pytest.mark.parametrize('entry', ['os', 'language'])
    def test_cli_entrypoints(self, tmp_path, entry):
        plan, context, app = ThermocyclerFixture().build(tmp_path, CYCLE_SOURCE)
        app.close()
        artifacts = tmp_path / 'cli-artifacts'
        module = 'culsma_os.cli' if entry == 'os' else 'culsma.cli'
        result = subprocess.run([sys.executable, '-m', module, 'run', str(tmp_path/'protocol.culs'),
            '--driver', 'opentrons-simulator', '--driver-config', str(context.config_path),
            '--artifacts-dir', str(artifacts)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads((artifacts/'run.json').read_text())
        assert receipt['ok'] and receipt['user_result']['os']['status'] == 'completed'


    def test_volume_tracks_confirmed_transfers(self, tmp_path, monkeypatch):
        source = SCALAR_SOURCE + 'with env(thermal=37C,duration=1s) { hold(w[0]); }'
        plan, context, app = ThermocyclerFixture().build(tmp_path, source)
        session = app.host.gateway.port.session
        seen = []
        original = session.backend.modules['cycler'].set_block_temperature
        def observe(*args, **kwargs):
            seen.append(kwargs['block_max_volume'])
            return original(*args, **kwargs)
        monkeypatch.setattr(session.backend.modules['cycler'], 'set_block_temperature', observe)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            assert seen == [50, 30]
            assert [r.payload['volume_basis'] for r in session.thermal.receipts] == ['language_material_state'] * 2
            assert TransferMatrixFixture().volumes(result) == (170, 30)
        finally: app.close()

    def test_group_uses_largest_well(self, tmp_path):
        source = DECLARATIONS.replace('p[A1]', 'p[A1:B1]') + ' w << [stock:20uL]; w[1] << [stock:50uL]; with env(thermal=37C,duration=1s) { hold(w); }'
        plan, context, app = ThermocyclerFixture().build(tmp_path, source)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            receipt = app.host.gateway.port.session.thermal.receipts[0]
            assert receipt.payload['block_max_volume_uL'] == 70
            assert [item['volume_uL'] for item in receipt.payload['request']['material_volumes']] == [20, 70]
        finally: app.close()

    @pytest.mark.parametrize('volume', [None, -1, True, float('nan'), float('inf')])
    def test_invalid_material_volume_rejects(self, tmp_path, volume):
        plan, context, app = ThermocyclerFixture().build(tmp_path)
        identity, pending = ThermalFixture().waiting_hold(app, plan)
        snapshot = deepcopy(pending.before_material_state)
        target = app.client.lifecycle.operations.planners['env_hold'].resolve_intent(pending).targets[0]
        snapshot['containers'][target.container_id]['volume_uL'] = volume
        before = list(app.host.gateway.port.session.backend.protocol.commands())
        try:
            with pytest.raises(ValueError):
                app.client.lifecycle.operations.planners['env_hold'].prepare(OperationPreparationRequest(
                    identity, replace(pending,before_material_state=snapshot),
                    tuple(s for p in plan.plans for s in p.steps if s.op == 'AllocContainer')))
            assert app.host.gateway.port.session.backend.protocol.commands() == before
            assert not app.host.gateway.port.session.thermal.receipts
        finally: app.close()

    @pytest.mark.parametrize('quantity', [
        {'dimension':'volume','status':'unknown','value':None},
        {'dimension':'mass','status':'unknown','value':None},
        {'dimension':'mass','value':10},
    ])
    def test_unavailable_volume_is_not_a_zero_surrogate(self, quantity):
        assert ProcessingMaterialVolumeInteractor().known_volume({
            'volume_uL':0, 'component_quantities':{'content':quantity}}) is None

