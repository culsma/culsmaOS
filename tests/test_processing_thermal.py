"""Functional expansion through the official virtual module and existing OS evidence chain."""
from dataclasses import replace
from pathlib import Path
import ast
import json
import subprocess
import sys

import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from .test_transfer_matrix import TransferMatrixFixture, BUFFER

DECLARATIONS = f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let p=plate(format="96well",capacity=100uL); let w=p[A1];'
HOLD = 'with env(thermal=37C,duration=1min) { hold(sample=w[0]); }'
SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + HOLD + ' stock << [w[0]:20uL];'


class ThermalFixture:
    def build(self, directory, source=SOURCE, configure=None):
        fixture = TransferMatrixFixture()
        plan = fixture.compile(source, directory)
        def configuration(raw):
            raw['modules'] = {'temperature': {'model': 'temperature module gen2', 'slot': '3'}}
            raw['labware']['assay'] = {'load_name': 'opentrons_96_aluminumblock_nest_wellplate_100ul', 'module': 'temperature'}
            allocations = [s for p in plan.plans for s in p.steps if s.op == 'AllocContainer']
            raw['bindings'] = {s.step_id: {'labware': 'tubes' if i == 0 else 'assay', 'well': 'A1' if i < 2 else 'B1'} for i,s in enumerate(allocations)}
            if configure:
                configure(raw)
        context = fixture.context(directory, plan, config_mutation=configuration)
        return plan, context, OSApplicationFactory().build(context)

    def waiting_hold(self, app, plan):
        app.client.start()
        identity = app.client.submit_run(RunRequest(plan, init_state(plan)))
        lifecycle = app.client.lifecycle
        lifecycle.runs.advance_ready(identity)
        lifecycle.operations.dispatch_ready(identity)
        lifecycle.runs.advance_ready(identity)
        pending = app.client.execution.pending(identity)
        assert pending.prepared.runtime_step.op == 'env_hold'
        return identity, pending


class TestThermalProcessing:
    def test_transfer_hold_transfer(self, tmp_path):
        plan, context, app = ThermalFixture().build(tmp_path)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            assert result.user_result['os']['status'] == 'completed'
            baseline = run(plan, StubDriver(), init_state(plan))
            assert baseline.ok and result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
            assert TransferMatrixFixture().volumes(result) == (170, 30)
            session = app.host.gateway.port.session
            assert len(session.backend.receipts) == 2 and len(session.thermal.receipts) == 1
            receipt = session.thermal.receipts[0]
            assert receipt.outcome == 'completed' and receipt.consumed_resources == {}
            assert receipt.payload['request']['temperature_celsius'] == 37
            assert receipt.payload['request']['duration_seconds'] == 60
            assert receipt.payload['sample_temperature_measured'] is False
            commands = session.backend.protocol.commands()
            assert len(commands) == 11 and 'Setting Temperature' in commands[4] and 'Delaying' in commands[5] and 'Deactivat' in commands[6]
            assert 'Aspirating 20' in commands[8]
            assert session.backend.available_tips() == 94
            assert not app.client.lifecycle.operations.resource.occupied()
            identity = result.user_result['os']['run_id']
            assert app.host.material.get(identity)[2] == 3
            connection = app.host.material.repository.connection
            assert connection.execute('SELECT count(*) FROM os_attempts').fetchone()[0] == 3
            assert connection.execute('SELECT count(*) FROM os_logical_completions').fetchone()[0] == 0
            assert app.client.lifecycle.reservations.get(identity).status == 'released'
        finally:
            app.close()

    @pytest.mark.parametrize('body', [
        'let temperature=37C; let interval=30s+30s; with env(thermal=temperature,duration=interval) { hold(sample=w[0]); }',
        'with env(thermal=37C,duration=0.5min) { hold(sample=w[0]); } with env(thermal=4C,duration=1s) { hold(sample=w[0]); }',
        'with env(thermal=95C,duration=1s) { hold(sample=w[0]); }',
    ])
    def test_values_and_repeated_holds(self, tmp_path, body):
        plan, context, app = ThermalFixture().build(tmp_path, DECLARATIONS + body)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            baseline = run(plan, StubDriver(), init_state(plan))
            assert result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
            assert len(app.host.gateway.port.session.thermal.receipts) == body.count('hold(')
            assert app.host.gateway.port.session.backend.available_tips() == 96
        finally: app.close()

    def test_complete_declared_group_on_module(self, tmp_path):
        source = DECLARATIONS.replace('p[A1]', 'p[A1:B1]') + ' w << [stock:20uL]; with env(thermal=37C,duration=1s) { hold(sample=w); }'
        plan, context, app = ThermalFixture().build(tmp_path, source)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            assert len(app.host.gateway.port.session.thermal.receipts[0].payload['request']['targets']) == 2
        finally: app.close()

    @pytest.mark.parametrize('kind', ['fractional', 'range', 'no-module', 'co2', 'nested', 'collateral'])
    def test_rejects_before_module_actions(self, tmp_path, kind):
        source = DECLARATIONS + HOLD
        configure = None
        if kind == 'fractional': source = source.replace('37C', '37.5C')
        if kind == 'range': source = source.replace('37C', '96C')
        if kind == 'co2': source = source.replace('thermal=37C', 'thermal=37C,co2=5%')
        if kind == 'nested': source = DECLARATIONS + 'with env(thermal=37C) { with env(thermal=37C,duration=1min) { hold(sample=w[0]); } }'
        if kind == 'collateral': source = DECLARATIONS + ' let other=p[B1]; ' + HOLD
        if kind == 'no-module':
            def configure(raw):
                raw.pop('modules')
                raw['labware']['assay'] = {'load_name': 'corning_96_wellplate_360ul_flat', 'slot': '3'}
        plan, context, app = ThermalFixture().build(tmp_path, source, configure)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result['os']['status'] == 'failed'
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert not app.host.gateway.port.session.thermal.receipts
            assert not app.client.lifecycle.operations.resource.occupied()
            assert 'PROCESSING_' in ' '.join(d.message for d in result.diagnostics)
        finally:
            app.close()

    @pytest.mark.parametrize('phase', ['set_temperature', 'hold', 'deactivate'])
    def test_unknown_hold_blocks_later_transfer(self, tmp_path, monkeypatch, phase):
        plan, context, app = ThermalFixture().build(tmp_path)
        session = app.host.gateway.port.session
        obj, method = (session.backend.protocol, 'delay') if phase == 'hold' else (session.backend.modules['temperature'], phase)
        def fail(*args, **kwargs):
            raise RuntimeError('injected module failure')
        monkeypatch.setattr(obj, method, fail)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result['os']['status'] == 'needs_reconciliation'
            assert len(session.backend.receipts) == 1 and session.thermal.receipts[0].outcome == 'unknown'
            assert TransferMatrixFixture().volumes(result) == (150, 50)
            assert app.client.lifecycle.operations.resource.occupied()
            identity = result.user_result['os']['run_id']
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

    def test_saved_processing_evidence_recovers_without_heat(self, tmp_path, monkeypatch):
        plan, context, app = ThermalFixture().build(tmp_path)
        identity, pending = ThermalFixture().waiting_hold(app, plan)
        ops = app.client.lifecycle.operations
        def crash(*args, **kwargs): raise KeyboardInterrupt('after saved processing receipt')
        monkeypatch.setattr(ops.material, 'reconcile', crash)
        try:
            with pytest.raises(KeyboardInterrupt): ops.dispatch_ready(identity)
            assert ops.evidence.find_evidence(pending.effect_id).outcome == 'completed'
            assert len(app.host.gateway.port.session.thermal.receipts) == 1
        finally: app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'completed'
            session = restarted.host.gateway.port.session
            assert not session.thermal.receipts and len(session.backend.receipts) == 1
            assert not any('Temperature Module temperature' in c for c in session.backend.protocol.commands())
            result = restarted.host.result(identity)
            assert TransferMatrixFixture().volumes(result) == (170, 30)
            assert restarted.host.material.get(identity)[2] == 3
        finally: restarted.close()

    def test_intent_without_evidence_never_reheats(self, tmp_path, monkeypatch):
        plan, context, app = ThermalFixture().build(tmp_path)
        identity, pending = ThermalFixture().waiting_hold(app, plan)
        def crash(*args, **kwargs): raise KeyboardInterrupt('after durable intent')
        monkeypatch.setattr(app.host.gateway, 'execute', crash)
        try:
            with pytest.raises(KeyboardInterrupt): app.client.lifecycle.operations.dispatch_ready(identity)
            assert not app.host.gateway.port.session.thermal.receipts
        finally: app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally: restarted.close()

    def test_processing_architecture(self):
        root = Path(__file__).resolve().parents[1] / 'src/culsma_os'
        assert {p.name for p in (root / 'processing_engine').glob('*.py')} == {'__init__.py', 'models.py'}
        tree = ast.parse((root / 'processing_engine/interactors/preparation.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('culsma_opentrons')
                assert not any('Repository' in n.name for n in node.names)
        scheduler = (root / 'scheduler/interactors.py').read_text()
        assert 'self.planners.get(operation)' in scheduler
        assert 'ProcessingInteractor' not in scheduler
        adapter = (root / 'driver_framework/adapters/opentrons.py').read_text()
        assert '.set_temperature' not in adapter and '.delay' not in adapter

    @pytest.mark.parametrize('entry', ['os', 'language'])
    def test_cli_thermal_hold(self, tmp_path, entry):
        plan, context, app = ThermalFixture().build(tmp_path)
        app.close()
        artifacts = tmp_path / 'cli-artifacts'
        module = 'culsma_os.cli' if entry == 'os' else 'culsma.cli'
        result = subprocess.run([sys.executable, '-m', module, 'run', str(tmp_path/'protocol.culs'),
            '--driver', 'opentrons-simulator', '--driver-config', str(context.config_path),
            '--artifacts-dir', str(artifacts)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        artifact = json.loads((artifacts/'run.json').read_text())
        assert artifact['ok'] and artifact['user_result']['os']['status'] == 'completed'
