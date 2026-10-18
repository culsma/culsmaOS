"""Incubate is a language workflow; heater execution is a selected instrument capability."""

import ast
import json
from pathlib import Path
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from .test_processing_agitation import AgitationFixture, DECLARATIONS, SHAKE
from .test_processing_thermal import ThermalFixture
from .test_transfer_matrix import TransferMatrixFixture

INCUBATE = 'Incubate(sample=w[0],temp=37C,duration=30s);'
SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + INCUBATE + ' ' + SHAKE + ' stock << [w[0]:20uL];'
HOLD_SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + INCUBATE + ' stock << [w[0]:20uL];'


class TestIncubationProcessing:
    def test_incubate_shake_transfer(self, tmp_path):
        plan, context, app = AgitationFixture().build(tmp_path, SOURCE)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            baseline = run(plan, StubDriver(), init_state(plan))
            assert baseline.ok and result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
            assert TransferMatrixFixture().volumes(result) == (170, 30)
            session = app.host.gateway.port.session
            assert len(session.thermal.receipts) == 1 and len(session.agitation.receipts) == 1
            assert len(session.backend.receipts) == 2
            assert session.thermal.receipts[0].payload['request']['material_volumes'][0]['volume_uL'] == 50
            commands = session.backend.protocol.commands()
            heat_done = next(i for i,c in enumerate(commands) if 'Deactivating Heater' in c)
            shake_start = next(i for i,c in enumerate(commands) if 'RPM' in c)
            assert heat_done < shake_start
            identity = result.user_result['os']['run_id']
            assert app.host.material.get(identity)[2] == 4
            assert app.client.lifecycle.reservations.get(identity).status == 'released'
            assert not app.client.lifecycle.operations.resource.occupied()
        finally: app.close()

    @pytest.mark.parametrize('temperature', [36, 96, 37.5])
    def test_unsupported_temperature_before_actions(self, tmp_path, temperature):
        plan, context, app = AgitationFixture().build(tmp_path, DECLARATIONS + INCUBATE.replace('37C',f'{temperature}C'))
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok and result.user_result['os']['status'] == 'failed'
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally: app.close()

    @pytest.mark.parametrize('phase,method', [('set_temperature','set_and_wait_for_temperature'),('hold','delay'),('deactivate_heater','deactivate_heater')])
    def test_unknown_incubation_blocks_transfer(self, tmp_path, monkeypatch, phase, method):
        plan, context, app = AgitationFixture().build(tmp_path, HOLD_SOURCE)
        session = app.host.gateway.port.session
        obj = session.backend.protocol if method == 'delay' else session.backend.modules['shaker']
        def fail(*args, **kwargs): raise RuntimeError('uncertain incubation')
        monkeypatch.setattr(obj,method,fail)
        try:
            result = app.execute(plan, init_state(plan))
            identity = result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status'] == 'needs_reconciliation'
            assert TransferMatrixFixture().volumes(result) == (150,50)
            assert len(session.backend.receipts) == 1
            assert session.thermal.receipts[0].payload['phases'][phase] == 'started'
            assert app.client.lifecycle.operations.resource.occupied()
        finally: app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity)
            restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally: restarted.close()

    def test_saved_incubation_receipt_recovers_without_reheating(self, tmp_path, monkeypatch):
        plan, context, app = AgitationFixture().build(tmp_path, HOLD_SOURCE)
        identity, pending = ThermalFixture().waiting_hold(app, plan)
        ops = app.client.lifecycle.operations
        def crash(*args, **kwargs): raise KeyboardInterrupt('after confirmed heater receipt')
        monkeypatch.setattr(ops.material,'reconcile',crash)
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
            assert not session.thermal.receipts and len(session.backend.receipts) == 1
            assert TransferMatrixFixture().volumes(restarted.host.result(identity)) == (170,30)
        finally: restarted.close()

    @pytest.mark.parametrize('entry', ['os','language'])
    def test_cli_incubation(self,tmp_path,entry):
        plan, context, app = AgitationFixture().build(tmp_path, SOURCE)
        app.close()
        artifacts = tmp_path/'cli-artifacts'
        result = subprocess.run([sys.executable,'-m','culsma_os.cli' if entry == 'os' else 'culsma.cli','run',
            str(tmp_path/'protocol.culs'),'--driver','opentrons-simulator','--driver-config',str(context.config_path),
            '--artifacts-dir',str(artifacts)],capture_output=True,text=True)
        assert result.returncode == 0, result.stdout+result.stderr
        assert json.loads((artifacts/'run.json').read_text())['user_result']['os']['status'] == 'completed'

    def test_volume_capture_architecture(self):
        root = Path(__file__).resolve().parents[1]/'src/culsma_os'
        tree = ast.parse((root/'processing_engine/interactors/material_volume.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').startswith(('culsma_opentrons','opentrons'))
                assert not any('Repository' in name.name for name in node.names)
        adapter = (root/'driver_framework/adapters/opentrons.py').read_text()
        assert '.set_and_wait_for_temperature' not in adapter
        assert '.capture(' not in adapter


    @pytest.mark.parametrize('platform', ['temperature','thermocycler'])
    def test_same_incubate_portal_on_other_thermal_instruments(self,tmp_path,platform):
        from .test_processing_thermocycler import ThermocyclerFixture
        fixture = ThermalFixture() if platform == 'temperature' else ThermocyclerFixture()
        plan, context, app = fixture.build(tmp_path,HOLD_SOURCE.replace('capacity=200uL','capacity=100uL'))
        try:
            result = app.execute(plan,init_state(plan))
            assert result.ok,[d.to_dict() for d in result.diagnostics]
            assert TransferMatrixFixture().volumes(result) == (170,30)
            assert len(app.host.gateway.port.session.thermal.receipts) == 1
        finally:app.close()

    def test_unsupported_centrifuge_has_no_device_actions(self,tmp_path):
        source = DECLARATIONS + 'agit(sample=w[0],mode=centrifuge,drive=1000g,duration=30s);'
        plan,context,app=AgitationFixture().build(tmp_path,source)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['status']=='failed'
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()
