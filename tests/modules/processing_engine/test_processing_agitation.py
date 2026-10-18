from tests.support.paths import ROOT
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
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER
from tests.support.processing_engine.processing_agitation import DECLARATIONS, SHAKE, SOURCE, AgitationFixture


class TestAgitationProcessing:
    def test_transfer_agitate_transfer(self, tmp_path):
        plan, context, app = AgitationFixture().build(tmp_path)
        try:
            result = app.execute(plan, init_state(plan))
            identity = AgitationFixture().compare_language(app, plan, result)
            assert TransferMatrixFixture().volumes(result) == (170, 30)
            session = app.host.gateway.port.session
            assert len(session.backend.receipts) == 2 and len(session.agitation.receipts) == 1
            receipt = session.agitation.receipts[0]
            assert receipt.outcome == 'completed' and receipt.consumed_resources == {}
            assert receipt.payload['request']['rate_rpm'] == 500 and receipt.payload['request']['duration_seconds'] == 30
            commands = session.backend.protocol.commands()
            assert len(commands) == 14 and 'Setting Heater-Shaker' in commands[6]
            assert 'Delaying' in commands[7] and 'Deactivating Shaker' in commands[8]
            assert all(r.module_action_results[0]['status'] == 'returned' for r in session.backend.receipts)
            assert session.backend.available_tips() == 94
            assert app.host.material.get(identity)[2] == 3
            assert app.client.lifecycle.reservations.get(identity).status == 'released'
            conn = app.host.material.repository.connection
            assert conn.execute('SELECT count(*) FROM os_attempts').fetchone()[0] == 3
            for (record,) in conn.execute('SELECT record FROM os_attempts'):
                assert 'simulation:opentrons:module:shaker' in json.loads(record)['context']['resource_ids']
            assert conn.execute('SELECT count(*) FROM os_logical_completions').fetchone()[0] == 0
            data = app.client.execution.host.codec.loads(app.client.get_run(identity).checkpoint)
            assert len(data['confirmed']) == 3
        finally: app.close()

    @pytest.mark.parametrize('kind', ['fractional', 'too-low', 'too-high', 'no-motion', 'linear', 'rotation', 'vortex',
                                     'environment', 'collateral', 'no-module', 'wrong-module'])
    def test_rejects_before_actions(self, tmp_path, kind):
        source = DECLARATIONS + SHAKE
        configure = None
        if kind == 'fractional': source = source.replace('500rpm', '500.5rpm')
        if kind == 'too-low': source = source.replace('500rpm', '199rpm')
        if kind == 'too-high': source = source.replace('500rpm', '3001rpm')
        if kind == 'no-motion': source = source.replace(',motion=orbital', '')
        if kind == 'linear': source = source.replace('motion=orbital', 'motion=linear').replace('500rpm', '2Hz')
        if kind == 'rotation': source = source.replace('motion=orbital', 'motion=rotation')
        if kind == 'vortex': source = source.replace('mode=shake,motion=orbital', 'mode=vortex')
        if kind == 'environment': source = DECLARATIONS + 'with env(thermal=37C) { ' + SHAKE + ' }'
        if kind == 'collateral': source = DECLARATIONS + 'let other=p[B1]; ' + SHAKE
        if kind == 'no-module':
            def configure(raw):
                raw.pop('modules')
                raw['labware']['assay'] = {'load_name': 'nest_96_wellplate_200ul_flat', 'slot': '6'}
        if kind == 'wrong-module':
            def configure(raw):
                raw['modules']['shaker']['model'] = 'temperature module gen2'
                raw['labware']['assay'] = {'load_name': 'opentrons_96_aluminumblock_nest_wellplate_100ul', 'module': 'shaker'}
            source = source.replace('capacity=200uL', 'capacity=100uL')
        plan, context, app = AgitationFixture().build(tmp_path, source, configure)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result['os']['status'] == 'failed'
            assert 'PROCESSING_' in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert not app.client.lifecycle.operations.resource.occupied()
        finally: app.close()

    @pytest.mark.parametrize('phase,method', [('close_latch','close_labware_latch'),('set_speed','set_and_wait_for_shake_speed'),
                                            ('hold','delay'),('deactivate','deactivate_shaker')])
    def test_unknown_blocks_following_transfer(self, tmp_path, monkeypatch, phase, method):
        plan, context, app = AgitationFixture().build(tmp_path)
        identity, pending = AgitationFixture().waiting_shake(app, plan)
        session = app.host.gateway.port.session
        obj = session.backend.protocol if method == 'delay' else session.backend.modules['shaker']
        def fail(*args, **kwargs): raise RuntimeError('injected agitation failure')
        monkeypatch.setattr(obj, method, fail)
        try:
            app.client.lifecycle.operations.dispatch_ready(identity)
            assert app.client.get_run(identity).status == 'needs_reconciliation'
            assert len(session.backend.receipts) == 1 and session.agitation.receipts[0].outcome == 'unknown'
            assert session.agitation.receipts[0].payload['phases'][phase] == 'started'
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.reservations.get(identity).status == 'active'
            assert app.host.material.get(identity)[2] == 1
        finally: app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally: restarted.close()

    def test_latch_failure_on_initial_transfer(self, tmp_path, monkeypatch):
        plan, context, app = AgitationFixture().build(tmp_path)
        session = app.host.gateway.port.session
        def fail(*args, **kwargs): raise RuntimeError('uncertain initial latch')
        monkeypatch.setattr(session.backend.modules['shaker'], 'close_labware_latch', fail)
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result['os']['status'] == 'needs_reconciliation'
            assert not session.agitation.receipts and session.backend.available_tips() == 96
            assert app.client.lifecycle.operations.resource.occupied()
            connection = app.host.material.repository.connection
            assert connection.execute('SELECT count(*) FROM os_attempts').fetchone()[0] == 1
            assert app.host.material.get(result.user_result['os']['run_id'])[2] == 0
        finally: app.close()

    @pytest.mark.parametrize('point', ['registration', 'checkpoint'])
    def test_completed_evidence_recovers_without_shaking(self, tmp_path, monkeypatch, point):
        plan, context, app = AgitationFixture().build(tmp_path)
        identity, pending = AgitationFixture().waiting_shake(app, plan)
        ops = app.client.lifecycle.operations
        def crash(*args, **kwargs): raise KeyboardInterrupt('after confirmed shake')
        monkeypatch.setattr(ops.material if point == 'registration' else ops.state, 'reconcile' if point == 'registration' else 'mark_ready', crash)
        try:
            with pytest.raises(KeyboardInterrupt): ops.dispatch_ready(identity)
            assert ops.evidence.find_evidence(pending.effect_id).outcome == 'completed'
        finally: app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'completed'
            session = restarted.host.gateway.port.session
            assert not session.agitation.receipts and len(session.backend.receipts) == 1
            result = restarted.host.result(identity)
            AgitationFixture().compare_language(restarted, plan, result)
            assert TransferMatrixFixture().volumes(result) == (170, 30)
            assert restarted.host.material.get(identity)[2] == 3
        finally: restarted.close()

    def test_missing_feedback_never_reissues(self, tmp_path, monkeypatch):
        plan, context, app = AgitationFixture().build(tmp_path)
        identity, pending = AgitationFixture().waiting_shake(app, plan)
        def crash(*args, **kwargs): raise KeyboardInterrupt('after intent')
        monkeypatch.setattr(app.host.gateway, 'execute', crash)
        try:
            with pytest.raises(KeyboardInterrupt): app.client.lifecycle.operations.dispatch_ready(identity)
            assert not app.host.gateway.port.session.agitation.receipts
        finally: app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally: restarted.close()

    @pytest.mark.parametrize('kind', ['group', 'values', 'boundary-low', 'boundary-high', 'repeated'])
    def test_group_scope_and_values(self, tmp_path, kind):
        source = DECLARATIONS + SHAKE
        if kind == 'group': source = source.replace('p[A1]', 'p[A1:B1]').replace('sample=w[0]', 'sample=w')
        if kind == 'values': source = DECLARATIONS + 'let speed=250rpm+250rpm; let period=0.5min; ' + SHAKE.replace('rate=500rpm', 'rate=speed').replace('duration=30s', 'duration=period')
        if kind == 'boundary-low': source = source.replace('500rpm', '200rpm')
        if kind == 'boundary-high': source = source.replace('500rpm', '3000rpm')
        if kind == 'repeated': source += SHAKE
        plan, context, app = AgitationFixture().build(tmp_path, source)
        try:
            result = app.execute(plan, init_state(plan))
            AgitationFixture().compare_language(app, plan, result)
            receipts = app.host.gateway.port.session.agitation.receipts
            assert len(receipts) == (2 if kind == 'repeated' else 1)
            assert len(receipts[0].payload['request']['targets']) == (2 if kind == 'group' else 1)
            assert app.host.gateway.port.session.backend.available_tips() == 96
        finally: app.close()

    @pytest.mark.parametrize('entry', ['os','language'])
    def test_cli_agitation(self, tmp_path, entry):
        plan, context, app = AgitationFixture().build(tmp_path)
        app.close()
        artifacts = tmp_path / 'cli-artifacts'
        result = subprocess.run([sys.executable, '-m', 'culsma_os.cli' if entry == 'os' else 'culsma.cli', 'run',
            str(tmp_path/'protocol.culs'), '--driver', 'opentrons-simulator', '--driver-config', str(context.config_path),
            '--artifacts-dir', str(artifacts)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        artifact = json.loads((artifacts/'run.json').read_text())
        assert artifact['ok'] and artifact['user_result']['os']['status'] == 'completed'

    def test_processing_boundaries(self):
        root = ROOT/'src/culsma_os'
        scheduler = (root/'scheduler/interactors.py').read_text()
        assert 'agit' not in scheduler and 'OrbitalShake' not in scheduler
        adapter = (root/'driver_framework/adapters/opentrons.py').read_text()
        assert '.set_and_wait_for_shake_speed' not in adapter and '.close_labware_latch' not in adapter
        source = (root/'processing_engine/interactors/preparation.py').read_text()
        assert 'self.intent_planners.get(' in source
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('culsma_opentrons')
                assert not any('Repository' in item.name for item in node.names)

