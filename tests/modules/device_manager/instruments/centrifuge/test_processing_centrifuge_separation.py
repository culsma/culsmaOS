from tests.support.paths import ROOT
from dataclasses import asdict, replace
import ast
from pathlib import Path
import pytest
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma.driver.stub import StubDriver
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.device_manager.models import DeviceConfigurationSnapshot, ExecutionFeedbackCapabilities
from culsma_os.driver_framework.interactors import NormalizedReceiptInteractor
from culsma_os.program_manager.models import HostBuildContext, RunRequest
from culsma_os.processing_engine.models import CentrifugeIntent, CentrifugeSeparationIntent
from culsma_os.processing_engine.interactors import CentrifugeMethodBindingInteractor
from culsma_os.transfer_engine.models import CentrifugeSupernatantTransferIntent
from tests.support.common import FakeDevicePort, TestAddress
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
from tests.support.processing_engine.processing_centrifuge_separation import BASE, SEP, TRANSFER, SOURCE, PROFILE, SeparationContractPort, SeparationContractFixture


class TestSeparation:
    @pytest.mark.parametrize('keep',[None,'supernatant','pellet'])
    def test_language_partition_and_following_transfer(self,tmp_path,keep):
        source=SOURCE if keep is None else SOURCE.replace('drive=500g','drive=500g,keep_source='+keep)
        fixture=SeparationContractFixture()
        plan,_,app=fixture.open(tmp_path,source)
        try:
            result=app.execute(plan,init_state(plan))
            assert result.ok,[d.to_dict() for d in result.diagnostics]
            baseline=run(plan,StubDriver(),init_state(plan))
            assert baseline.ok and result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
            assert result.state.artifacts['protocol_outputs']==baseline.state.artifacts['protocol_outputs']
            intent=fixture.port.processing[0]
            assert intent.program_kind=='centrifuge_program' and intent.method_profile.profile_id=='test_method'
            assert intent.duration_seconds==1 and len(fixture.port.processing)==1
            transfer=fixture.port.transfers[0]
            assert type(transfer) is CentrifugeSupernatantTransferIntent
            assert transfer.selected_slot=='0' and transfer.producer_step_id==intent.step_id
            assert transfer.aliquots[0].source==intent.targets[0] and transfer.aliquots[0].volume_uL==40
            state=result.state.artifacts['material_state']
            assert sorted(c['volume_uL'] for c in state['containers'].values())==[10,40]
            identity=result.user_result['os']['run_id']
            assert app.host.material.get(identity)[2]==2
            assert not app.client.lifecycle.operations.resource.occupied()
        finally:app.close()

    @pytest.mark.parametrize('profile',[None,{},dict(PROFILE,duration_seconds=0),dict(PROFILE,duration_seconds=float('nan')),
        dict(PROFILE,duration_seconds=True),dict(PROFILE,revision='')])
    def test_profile_rejection(self,tmp_path,profile):
        fixture=SeparationContractFixture(profile)
        plan,_,app=fixture.open(tmp_path)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['status']=='failed'
            assert 'PROCESSING_METHOD_PROFILE_' in ' '.join(d.message for d in result.diagnostics)
            assert not fixture.port.executions
            assert not app.client.lifecycle.operations.resource.occupied()
        finally:app.close()

    def test_unknown_blocks_partition_and_transfer(self,tmp_path):
        fixture=SeparationContractFixture(fail=True)
        plan,context,app=fixture.open(tmp_path)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['status']=='needs_reconciliation'
            identity=result.user_result['os']['run_id']
            _,material,version=app.host.material.get(identity)
            assert version==0 and not material.get('contents_states')
            assert not fixture.port.transfers and len(fixture.port.processing)==1
            assert app.client.lifecycle.operations.resource.occupied()
        finally:app.close()
        fresh=SeparationContractFixture()
        restarted=OSApplicationFactory({'fake':fresh}).build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='needs_reconciliation'
            assert not fresh.port.executions
        finally:restarted.close()

    @pytest.mark.parametrize('point',['registration','checkpoint'])
    def test_recovery_uses_saved_evidence(self,tmp_path,monkeypatch,point):
        fixture=SeparationContractFixture()
        plan,context,app=fixture.open(tmp_path)
        identity,pending=fixture.waiting(app,plan)
        ops=app.client.lifecycle.operations
        def crash(*args,**kwargs):raise KeyboardInterrupt('after saved separation receipt')
        monkeypatch.setattr(ops.material if point=='registration' else ops.state,
            'reconcile' if point=='registration' else 'mark_ready',crash)
        try:
            with pytest.raises(KeyboardInterrupt):ops.dispatch_ready(identity)
            assert ops.evidence.find_evidence(pending.effect_id).outcome=='completed'
        finally:app.close()
        fresh=SeparationContractFixture()
        restarted=OSApplicationFactory({'fake':fresh}).build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='completed'
            assert not fresh.port.processing and len(fresh.port.transfers)==1
            assert restarted.host.result(identity).state.artifacts['material_state']==run(plan,StubDriver()).state.artifacts['material_state']
        finally:restarted.close()

    @pytest.mark.parametrize('kind',['pellet','missing-capability','environment'])
    def test_typed_selection_rejection(self,tmp_path,kind):
        source=SOURCE
        if kind=='pellet':source=BASE+SEP+'d << [s.contents[1]:0uL];'
        if kind=='environment':source=BASE+'with env(thermal=22C,duration=1s) {'+SEP+'}'
        fixture=SeparationContractFixture(selection=kind!='missing-capability')
        plan,_,app=fixture.open(tmp_path,source)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert not fixture.port.transfers
            assert not fixture.port.processing  # Whole-program preflight rejects before separation too.
            assert result.user_result['os']['preflight']['status']=='rejected'
        finally:app.close()

    def test_unbound_request_and_profile_identity(self):
        from culsma_os.workspace_manager.models import ResolvedContainerRef
        request=CentrifugeSeparationIntent('step',(ResolvedContainerRef('sample'),),500.5,'rpm')
        intent=CentrifugeMethodBindingInteractor().bind(request,{'method_profiles':{'centrifuge_program':PROFILE}})
        assert type(intent) is CentrifugeIntent and intent.drive_value==500.5 and intent.drive_unit=='rpm'
        assert intent.method_profile.revision=='method-r1'
        assert CentrifugeMethodBindingInteractor().bind(replace(intent,method_profile=None),{})==replace(intent,method_profile=None)

    def test_static_admission_without_centrifuge(self,tmp_path):
        from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
        plan=TransferMatrixFixture().compile(SOURCE,tmp_path)
        diagnostics=HostedRuntimeInteractor(processing_capabilities={}).validate_plan(plan)
        assert any(d.code=='HOST_OPERATION_UNSUPPORTED' for d in diagnostics)
        assert not HostedRuntimeInteractor(processing_capabilities={'centrifuge':{'rotor':{'labware':['loaded']}}}).validate_plan(plan)

    def test_device_free_queued_checkpoint_rechecked(self,tmp_path):
        from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
        plan=TransferMatrixFixture().compile(SOURCE,tmp_path)
        submitted=HostedRuntimeInteractor().create(plan,init_state(plan),'queued')
        worker=HostedRuntimeInteractor(processing_capabilities={})
        rejected=worker.advance(submitted)
        assert worker.pending(rejected) is None
        result=worker.result(rejected)
        assert not result.ok and any(d.code=='HOST_OPERATION_UNSUPPORTED' for d in result.diagnostics)
        assert not result.state.artifacts.get('material_state',{}).get('contents_states')

    def test_checkpoint_enum(self):
        from culsma.domains.separation import CentrifugeProgramOutput
        from culsma_os.program_manager.interactors.codec import RuntimeCheckpointCodecInteractor
        from culsma_os.program_manager.models import HostContractError
        codec=RuntimeCheckpointCodecInteractor()
        for value in CentrifugeProgramOutput:
            assert codec.loads(codec.dumps(value)) is value
        with pytest.raises(HostContractError):codec.decode({'t':'enum','c':'untrusted.module.Type','v':'PELLET'})
        with pytest.raises(HostContractError):codec.decode({'t':'enum','c':'CentrifugeProgramOutput','v':'missing'})

    def test_architecture(self):
        root=ROOT/'src/culsma_os'
        for module in ['processing_engine/interactors/centrifuge.py','transfer_engine/interactors.py']:
            for node in ast.walk(ast.parse((root/module).read_text())):
                if isinstance(node,ast.ImportFrom):
                    assert not (node.module or '').startswith(('culsma_opentrons','pylabrobot','culsma_pylabrobot'))
                    assert not any('Repository' in n.name for n in node.names)
        gateway=(root/'driver_framework/interactors.py').read_text()
        assert 'def require_selection(' in gateway
        assert 'CentrifugeSeparationIntent' not in gateway

