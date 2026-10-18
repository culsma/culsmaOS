from tests.support.paths import ROOT
from copy import deepcopy
from dataclasses import replace
import ast
from pathlib import Path
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.multichannel import MultichannelOSFixture
from tests.support.transfer_engine.plate96 import BUFFER
from tests.support.transfer_engine.multichannel_plate import SOURCE, WholePlateFixture


class TestMultichannelPlateOS:
    @pytest.mark.parametrize('pipette',['p20_multi_gen2','p300_multi_gen2'])
    def test_plate_uses_twelve_waves_and_matches_language(self,tmp_path,pipette):
        plan,context,app=WholePlateFixture().build(tmp_path,pipette=pipette)
        calls=[];original=app.client.lifecycle.operations.groups.dispatch
        def count(*args):calls.append(1);return original(*args)
        app.client.lifecycle.operations.groups.dispatch=count
        try:
            result=app.execute(plan,init_state(plan))
            assert result.ok,[d.to_dict() for d in result.diagnostics]
            assert result.state.artifacts['material_state']==run(plan,StubDriver()).state.artifacts['material_state']
            assert calls==[1]
            backend=app.host.gateway.port.session.backend
            assert len(backend.receipts)==12 and backend.available_tips()==0
            assert [r.operation.commands[0].target_address.well for r in backend.receipts]==[f'A{i}' for i in range(1,13)]
            run_id=result.user_result['os']['run_id']
            evidence=app.client.lifecycle.evidence
            data=app.client.execution.host.codec.loads(app.client.get_run(run_id).checkpoint)
            resolution=data['confirmed'][0].resolution
            assert len(resolution.members)==96
            assert evidence.known_consumption('opentrons')=={'tips':96}
            attempt=evidence.find_attempt(resolution.effect_id)
            certificate=attempt.context['description']['reorder_certificate']
            assert certificate['semantic_effect_ids']!=certificate['physical_effect_ids']
            receipts=[app.client.lifecycle.operations.material.repository.receipt(m.effect_id) for m in resolution.members]
            assert any(r.semantic_state_fingerprint!=r.proposed_state_fingerprint for r in receipts)
            assert WholePlateFixture().volumes(app,run_id)=={'Stock':80,**{f'Assay_{r}{c}':20 for r in 'ABCDEFGH' for c in range(1,13)}}
            assert not app.client.lifecycle.operations.resource.occupied()
        finally:app.close()

    def test_projection_certifies_exact_final_state(self,tmp_path):
        plan,context,app=WholePlateFixture().build(tmp_path)
        try:
            run_id,pending=WholePlateFixture().pending(app,plan)
            operations=app.client.lifecycle.operations
            from culsma_os.transfer_engine.models import TransferRequest
            prepared=operations.transfer.prepare_group(TransferRequest(run_id,pending,app.client.execution.allocations(run_id)))
            projections=operations.groups.projection.prepare(pending,prepared.description['waves'])
            assert projections[-1].after==pending.members[-1].prepared.material_result.material_state
            assert [p.effect_id for p in projections[:8]]==[pending.members[i].effect_id for i in range(0,96,12)]
            damaged=deepcopy(pending)
            damaged.members[12].prepared.material_result.material_state['containers'].clear()
            with pytest.raises(ValueError,match='REORDER'):
                operations.groups.projection.prepare(damaged,prepared.description['waves'])
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()

    @pytest.mark.parametrize('column',[1,3,12])
    def test_middle_wave_unknown_preserves_nonprefix_members(self,tmp_path,monkeypatch,column):
        fixture=WholePlateFixture();plan,context,app=fixture.build(tmp_path)
        run_id,pending=fixture.pending(app,plan)
        backend=app.host.gateway.port.session.backend
        original=backend.pipette.dispense;calls=[]
        def fail(volume,location):
            calls.append(location.well_name)
            if len(calls)==column:raise RuntimeError('unknown shared column')
            return original(volume,location)
        monkeypatch.setattr(backend.pipette,'dispense',fail)
        try:
            record = app.client.run_until_settled(run_id)
            assert record.status=='needs_reconciliation', record.error
            assert len(calls)==column and len(backend.receipts)==column-1
            volumes=fixture.volumes(app,run_id)
            assert volumes['Stock']==2000-160*(column-1)
            assert all(volumes[f'Assay_{row}{col}']==(20 if col<column else 0) for row in 'ABCDEFGH' for col in range(1,13))
            uncertain={pending.members[row*12+column-1].effect_id for row in range(8)}
            assert set(app.client.lifecycle.operations.material.uncertainties(run_id))==uncertain
            assert app.client.lifecycle.evidence.known_consumption('opentrons')=={'tips':8*column}
            assert app.client.lifecycle.operations.resource.occupied()
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert set(restarted.client.lifecycle.operations.material.uncertainties(run_id))==uncertain
            assert fixture.volumes(restarted,run_id)==volumes
            assert restarted.host.gateway.port.session.backend.available_tips()==96-8*column
        finally:restarted.close()

    @pytest.mark.parametrize('crash_point',['last-wave-registration','resume','transaction'])
    def test_plate_recovery_from_saved_wave_evidence(self,tmp_path,monkeypatch,crash_point):
        fixture=WholePlateFixture();plan,context,app=fixture.build(tmp_path)
        run_id,pending=fixture.pending(app,plan)
        material=app.client.lifecycle.operations.material
        if crash_point=='resume':
            def crash(*args):raise KeyboardInterrupt('before semantic resume')
            monkeypatch.setattr(app.client.lifecycle.operations.state,'mark_ready',crash)
        elif crash_point=='last-wave-registration':
            original=material.reconcile_projected_wave;calls=[]
            def crash(*args):
                calls.append(1)
                if len(calls)==12:raise KeyboardInterrupt('last wave saved')
                return original(*args)
            monkeypatch.setattr(material,'reconcile_projected_wave',crash)
        else:
            original=material.repository.commit_in_transaction;calls=[]
            def crash(*args):
                calls.append(1)
                if len(calls)==93:raise KeyboardInterrupt('inside last wave transaction')
                return original(*args)
            monkeypatch.setattr(material.repository,'commit_in_transaction',crash)
        try:
            with pytest.raises(KeyboardInterrupt):app.client.lifecycle.operations.dispatch_ready(run_id)
            assert len(app.host.gateway.port.session.backend.receipts)==12
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status=='completed'
            assert restarted.client.result(run_id).state.artifacts['material_state']==run(plan,StubDriver()).state.artifacts['material_state']
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.evidence.known_consumption('opentrons')=={'tips':96}
            assert not restarted.client.lifecycle.operations.resource.occupied()
        finally:restarted.close()

    def test_plate_intent_without_evidence_never_replays(self,tmp_path,monkeypatch):
        fixture=WholePlateFixture();plan,context,app=fixture.build(tmp_path)
        run_id,pending=fixture.pending(app,plan)
        evidence=app.client.lifecycle.evidence;original=evidence.ingest
        def crash(value):
            if value.payload.get('evidence_scope')=='shared_eight_channel_wave' and value.payload['member_step_ids'][0].endswith('.g2'):
                raise KeyboardInterrupt('third column before durable evidence')
            return original(value)
        monkeypatch.setattr(evidence,'ingest',crash)
        try:
            with pytest.raises(KeyboardInterrupt):app.client.lifecycle.operations.dispatch_ready(run_id)
            assert len(app.host.gateway.port.session.backend.receipts)==3
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert fixture.volumes(restarted,run_id)['Stock']==1680
            assert len(restarted.client.lifecycle.operations.material.uncertainties(run_id))==8
        finally:restarted.close()

    def test_wave_consumption_is_not_double_counted(self,tmp_path):
        plan,context,app=WholePlateFixture().build(tmp_path)
        try:
            result=app.execute(plan,init_state(plan));assert result.ok
            run_id=result.user_result['os']['run_id']
            effect=app.client.execution.host.codec.loads(app.client.get_run(run_id).checkpoint)['confirmed'][0].effect_id
            evidence=app.client.lifecycle.evidence
            assert evidence.find_evidence(effect).consumed_resources=={}
            ids=evidence.find_attempt(effect).context['description']['waves']
            assert [evidence.find_evidence(w['effect_id']).consumed_resources for w in ids]==[{'tips':8}]*12
        finally:app.close()

    def test_gated_plate_is_rejected_before_physical_reordering(self,tmp_path):
        source=SOURCE.replace('assay[A1:H12] << [stock:20uL];','let flag=true; flag=false; flag=true; if flag { assay[A1:H12] << [stock:20uL]; }')
        plan,context,app=WholePlateFixture().build(tmp_path,source)
        # A static if-true is folded away; this fixture must retain a real gate.
        group = next(s for p in plan.plans for s in p.steps if s.op == 'MutationGroup')
        assert group.gate.get('runtime_conditions')
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert any('TRANSFER_REORDER_PROFILE_UNSUPPORTED' in d.message for d in result.diagnostics)
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert not app.client.lifecycle.operations.resource.occupied()
        finally:app.close()

    def test_wave_boundaries_keep_language_and_vendor_independent(self):
        root=ROOT/'src/culsma_os'
        for name in ['scheduler/interactors.py','program_manager/interactors/projection.py','material_system/interactors.py']:
            text=(root/name).read_text()
            assert 'culsma_opentrons' not in text and 'pick_up_tip' not in text
        imports=[n.module or '' for n in ast.walk(ast.parse((root/'program_manager/interactors/projection.py').read_text())) if isinstance(n,ast.ImportFrom)]
        assert 'culsma.runtime.material.compute' in imports
        assert not any('.repositories' in n for n in imports)

