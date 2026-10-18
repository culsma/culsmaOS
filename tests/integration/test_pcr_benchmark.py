from pathlib import Path
import hashlib
import json
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
from tests.support.integration.pcr_benchmark import EXAMPLE, PCRFixture


class TestPCRBenchmark:
    def test_source_provenance(self):
        original = (EXAMPLE/'protocol.original.culs').read_text()
        adapted = (EXAMPLE/'protocol.culs').read_text()
        expected = json.loads((EXAMPLE/'expected.json').read_text())
        assert hashlib.sha256(original.encode()).hexdigest() == expected['original_sha256']
        assert original == adapted

    def test_complete_protocol(self, tmp_path, record_property):
        f = PCRFixture(); plan, context, app = f.build(tmp_path)
        try:
            result = app.execute(plan, init_state(plan))
            assert result.ok, [d.to_dict() for d in result.diagnostics]
            assert result.user_result['os']['status'] == 'completed'
            baseline = run(plan, StubDriver(), init_state(plan)); assert baseline.ok
            assert result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
            assert result.state.artifacts['protocol_outputs'] == baseline.state.artifacts['protocol_outputs']
            assert TransferMatrixFixture().volumes(result) == (0,0,0,0,0,50)
            identity = result.user_result['os']['run_id']; session = app.host.gateway.port.session
            holds = session.thermal.receipts
            assert [(r.payload['request']['temperature_celsius'],r.payload['request']['duration_seconds']) for r in holds] == f.schedule()
            assert sum(r.payload['request']['duration_seconds'] for r in holds) == 2130
            assert len({r.step_id for r in holds}) == 92
            assert all(r.outcome == 'completed' and r.payload['block_max_volume_uL'] == 50 for r in holds)
            assert all(not r.payload['sample_temperature_measured'] for r in holds)
            assert all(r.payload['phases']['deactivate_lid'] == 'returned' for r in holds)
            assert all(not any('Opening Thermocycler' in c for c in r.payload['commands']) for r in holds)
            strokes = [c.volume_uL for r in session.backend.receipts for c in r.operation.commands]
            assert strokes == [1,2.5,2.5,12.5,12.5,19]
            receipt = session.backend.receipts[0].to_payload()
            resolutions = receipt['constraint_resolution']
            assert [v['requirement'] for v in resolutions] == ['high_precision','low_carryover']
            assert resolutions[0]['method_id'] == 'pcr-p20-explicit-flow'
            assert receipt['instrument']['aspirate_flow_rate_uL_s'] == 5
            assert receipt['instrument']['dispense_flow_rate_uL_s'] == 10
            assert session.backend.available_tips() == 90
            session.backend.thermocycler_access.require_inactive('cycler')
            assert app.client.lifecycle.reservations.get(identity).status == 'released'
            assert not app.client.lifecycle.operations.resource.occupied()
            assert len(app.client.lifecycle.operations.evidence.attempts_for_run(identity)) == 93
            assert app.host.material.get(identity)[2] == 93
            record_property('acceptance', json.dumps({'thermal_holds':len(holds),'strokes_uL':strokes,
                'product_uL':50,'programmed_hold_seconds':2130,'reservation':'released','language_state_equivalent':True}))
        finally: app.close()

    def test_missing_precision_method_rejects_before_commands(self, tmp_path):
        plan, _, app = PCRFixture().build(tmp_path, configure=lambda raw:raw['transfer_policy'].pop('precision_method'))
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok
            assert 'TRANSFER_CONSTRAINT_UNSUPPORTED' in ' '.join(d.message for d in result.diagnostics)
            assert result.user_result['os']['preflight']['status']=='rejected'
            assert 'registered_material' not in result.user_result['os']
            assert not app.client.lifecycle.evidence.attempts_for_run(result.user_result['os']['run_id'])
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert not app.client.lifecycle.operations.resource.occupied()
        finally: app.close()

    @pytest.mark.parametrize('temperature',[3,100])
    def test_module_bounds_reject_before_commands(self, tmp_path, temperature):
        plan, _, app = PCRFixture().build(tmp_path, change=lambda s:s.replace('98C',f'{temperature}C'))
        try:
            result = app.execute(plan, init_state(plan))
            assert not result.ok
            assert result.user_result['os']['preflight']['status'] == 'rejected'
            assert 'PROCESSING_TEMPERATURE_UNSUPPORTED' in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally: app.close()

    @pytest.mark.parametrize('method',['set_lid_temperature','set_block_temperature','deactivate_lid'])
    def test_unknown_blocks_following_hold_and_restart(self, tmp_path, monkeypatch, method):
        plan, context, app = PCRFixture().build(tmp_path)
        session = app.host.gateway.port.session
        module = session.backend.modules['cycler']; original = getattr(module,method)
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError('PCR device completion unknown')
        monkeypatch.setattr(module,method,fail)
        try:
            result = app.execute(plan, init_state(plan)); assert not result.ok
            identity = result.user_result['os']['run_id']
            assert result.user_result['os']['status'] == 'needs_reconciliation'
            assert len(session.thermal.receipts) == 1 and session.thermal.receipts[0].outcome == 'unknown'
            assert app.host.material.get(identity)[2] == 1
            assert app.client.lifecycle.reservations.get(identity).status == 'active'
            assert app.client.lifecycle.operations.resource.occupied()
        finally: app.close()
        restarted = OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity); restarted.client.start()
            assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally: restarted.close()

