from dataclasses import replace,asdict
import json,sqlite3
import pytest
from culsma.domains.constraints.contracts import CONSTRAINT_REQUIREMENTS,ConstraintRequirement
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.transfer_engine.interactors import TransferConstraintInteractor
from culsma_os.device_manager.models import DeviceConfigurationSnapshot
from culsma_os.device_manager.repository import SqliteDeviceRepository
from culsma_os.program_manager.models import RunRequest
from tests.support.integration.pcr_benchmark import PCRFixture


class TestTransferConstraints:
    @pytest.mark.parametrize('typed',[False,True])
    def test_requirements_survive_typed_resolution(self,typed):
        requirement=ConstraintRequirement.HIGH_PRECISION
        payload={'requirements':[requirement if typed else requirement.value,'low_carryover'],'options':{}}
        if typed:payload['requirement_types']={requirement.value:CONSTRAINT_REQUIREMENTS.current.encode(requirement)}
        assert TransferConstraintInteractor().resolve(payload)==('high_precision','low_carryover')

    @pytest.mark.parametrize('payload',[
        {'requirements':['unknown']}, {'requirements':[12]}, {'requirements':['high_precision'],'options':{'accuracy':0.01}},
        {'requirements':['high_precision'],'requirement_types':{'low_carryover':{'kind':'DomainEnum'}}},
        {'requirements':'high_precision'}, {'requirements':[],'extra':True},
    ])
    def test_invalid_constraints_reject(self,payload):
        with pytest.raises(ValueError,match='TRANSFER_CONSTRAINT_INVALID'):TransferConstraintInteractor().resolve(payload)

    def test_unsupported_device_rejects_during_preflight(self,tmp_path):
        plan,_,app=PCRFixture().build(tmp_path,configure=lambda r:r['transfer_policy'].pop('precision_method'))
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['preflight']['status']=='rejected'
            assert 'TRANSFER_CONSTRAINT_UNSUPPORTED' in ' '.join(d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()

    def test_resolved_request_and_frozen_plan_preserve_methods(self,tmp_path):
        plan,_,app=PCRFixture().build(tmp_path)
        try:
            app.client.start();identity=app.client.submit_run(RunRequest(plan,init_state(plan)))
            app.client.lifecycle.runs.advance_ready(identity)
            pending=app.client.execution.pending(identity)
            from culsma_os.transfer_engine.models import TransferRequest
            prepared=app.client.lifecycle.operations.transfer.prepare(TransferRequest(identity,pending,app.client.execution.allocations(identity)))
            assert prepared.intent.requirements==('high_precision','low_carryover')
            methods=prepared.description['constraint_resolution']
            assert [m['requirement'] for m in methods]==list(prepared.intent.requirements)
            assert methods[0]['parameters']['aspirate_flow_rate_uL_s']==5
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()

    def test_capability_snapshot_round_trip_and_legacy(self):
        snapshot=DeviceConfigurationSnapshot('test','simulation','r1',(),transfer_requirements=('high_precision','low_carryover'))
        restored=SqliteDeviceRepository.decode_snapshot(json.dumps(asdict(snapshot)))
        assert restored==snapshot
        payload=asdict(snapshot);payload.pop('transfer_requirements')
        assert SqliteDeviceRepository.decode_snapshot(json.dumps(payload)).transfer_requirements==()

    @pytest.mark.parametrize('fault',['device','method-receipt'])
    def test_unknown_transfer_blocks_pcr_and_restart(self,tmp_path,monkeypatch,fault):
        plan,context,app=PCRFixture().build(tmp_path);session=app.host.gateway.port.session
        if fault=='device':
            original=session.backend.pipette.aspirate
            def fail(*args,**kwargs):
                original(*args,**kwargs);raise TimeoutError('constraint transfer acknowledgment lost')
            monkeypatch.setattr(session.backend.pipette,'aspirate',fail)
        else:
            original=session.backend.build_receipt
            def corrupt(*args,**kwargs):
                receipt=original(*args,**kwargs)
                return replace(receipt,operation=replace(receipt.operation,constraint_resolution=()))
            monkeypatch.setattr(session.backend,'build_receipt',corrupt)
        try:
            result=app.execute(plan,init_state(plan));identity=result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status']=='needs_reconciliation'
            assert not session.thermal.receipts
            assert app.client.lifecycle.reservations.get(identity).status=='active'
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.host.material.get(identity)[2]==0
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally:restarted.close()

