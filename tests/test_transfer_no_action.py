"""Language-owned no-motion effects complete without pretending a robot acted."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import ast
import json
import sqlite3
import subprocess
import sys

import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from culsma_os.event_journal.models import AttemptRecord
from .test_transfer_matrix import TransferMatrixFixture, BUFFER
from .test_plate96 import PlateFixture
from .test_multichannel import MultichannelOSFixture, SOURCE as COLUMN_SOURCE


class NoActionFixture:
    def build(self, directory, body, load=f'{BUFFER}:200uL'):
        fixture=TransferMatrixFixture()
        plan=fixture.compile(fixture.source(body,load),directory)
        context=fixture.context(directory,plan)
        return plan,context,OSApplicationFactory().build(context)

    def pending(self,app,plan):
        app.client.start()
        identity=app.client.submit_run(RunRequest(plan,init_state(plan)))
        app.client.lifecycle.runs.advance_ready(identity)
        return identity,app.client.execution.pending(identity)

    def assert_complete(self,app,plan,result,logical_count,physical_count):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan,StubDriver(),init_state(plan))
        assert baseline.ok and result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        backend=app.host.gateway.port.session.backend
        assert len(backend.receipts)==physical_count
        assert backend.available_tips()==96-physical_count
        assert not app.client.lifecycle.operations.resource.occupied()
        run_id=result.user_result['os']['run_id']
        assert app.host.material.get(run_id)[1]==result.state.artifacts['material_state']
        owner=app.client.lifecycle.reservations.get(run_id)
        assert owner is not None and owner.status=='released'
        conn=app.host.material.repository.connection
        assert conn.execute('SELECT count(*) FROM os_logical_completions').fetchone()[0]==logical_count
        for (payload,) in conn.execute('SELECT record FROM os_logical_completions'):
            record=json.loads(payload)
            assert record['payload']=={'completion_kind':'logical','device_action':False}
            assert conn.execute('SELECT count(*) FROM os_attempts WHERE effect_id=?',(record['effect_id'],)).fetchone()[0]==0
            assert conn.execute('SELECT count(*) FROM os_evidence WHERE effect_id=?',(record['effect_id'],)).fetchone()[0]==0
        return run_id


class TestTransferNoAction:
    @pytest.mark.parametrize('body,load',[
        ('target << [source:0uL];',f'{BUFFER}:200uL'),
        ('let n=20uL-20uL; target << [source:n];',f'{BUFFER}:200uL'),
        ('source << [source:50uL];',f'{BUFFER}:200uL'),
        ('source << [source];',f'{BUFFER}:200uL'),
        ('let alias=source; alias << [source:50uL];',f'{BUFFER}:200uL'),
        ('target << [source];',f'{BUFFER}:0uL'),
    ])
    def test_scalar_no_action(self,tmp_path,body,load,monkeypatch):
        plan,context,app=NoActionFixture().build(tmp_path,body,load)
        def forbidden(*args,**kwargs):raise AssertionError('no-motion effect reached physical preparation')
        monkeypatch.setattr(app.host.gateway,'prepare',forbidden)
        monkeypatch.setattr(app.client.lifecycle.operations.resource,'acquire',forbidden)
        try:
            result=app.execute(plan,init_state(plan))
            NoActionFixture().assert_complete(app,plan,result,1,0)
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()

    @pytest.mark.parametrize('body',[
        'target << [source:0uL,source:50uL];',
        'target << [source:50uL,source:0uL];',
        'target << [target:50uL,source:50uL];',
        'target << [source:50uL,target];',
        'target << [source:50uL]; source << [source:20uL]; target << [source:0uL]; target << [source:50uL];',
    ])
    def test_mixed_sources_keep_real_movements(self,tmp_path,body):
        plan,context,app=NoActionFixture().build(tmp_path,body)
        try:
            physical=2 if body.count(';')>1 else 1
            logical=2 if physical==2 else 0
            result=app.execute(plan,init_state(plan))
            NoActionFixture().assert_complete(app,plan,result,logical,physical)
        finally:app.close()

    @pytest.mark.parametrize('amounts,logical_count,physical_count',[
        ('0uL,20uL,0uL,20uL',2,2),
        ('20uL,0uL,20uL,0uL',2,2),
        ('0uL,0uL,0uL,0uL',4,0),
    ])
    def test_group_member_order_and_receipt_provenance(self,tmp_path,amounts,logical_count,physical_count):
        source=f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let assay=plate(format="96well",capacity=200uL); assay[A1:A4] << [series(stock,[{amounts}])];'
        plan,context,app=PlateFixture().run_case(tmp_path,source,'p20_single_gen2')
        try:
            result=app.execute(plan,init_state(plan))
            identity=NoActionFixture().assert_complete(app,plan,result,logical_count,physical_count)
            data=app.client.execution.host.codec.loads(app.client.get_run(identity).checkpoint)
            values=data['confirmed'][0].resolution.members
            assert len(values)==4
            assert sum(v.code=='OS_TRANSFER_NO_ACTION' for v in values)==logical_count
            assert all(v.payload.get('device_action') is False for v in values if v.code=='OS_TRANSFER_NO_ACTION')
        finally:app.close()

    @pytest.mark.parametrize('point',['logical_record','material_registration','checkpoint'])
    def test_no_action_restart_is_idempotent(self,tmp_path,monkeypatch,point):
        plan,context,app=NoActionFixture().build(tmp_path,'target << [source:0uL]; target << [source:50uL];')
        run_id,pending=NoActionFixture().pending(app,plan)
        ops=app.client.lifecycle.operations
        def crash(*args,**kwargs):raise KeyboardInterrupt('injected logical completion crash')
        if point=='logical_record':monkeypatch.setattr(ops.material,'reconcile_logical',crash)
        elif point=='material_registration':monkeypatch.setattr(ops.state,'mark_ready',crash)
        else:
            original=app.client.execution.host.resume
            def after_resume(*args,**kwargs):original(*args,**kwargs);crash()
            monkeypatch.setattr(app.client.execution.host,'resume',after_resume)
        try:
            with pytest.raises(KeyboardInterrupt):ops.dispatch_ready(run_id)
            assert ops.evidence.find_logical_completion(pending.effect_id)
            assert ops.evidence.find_attempt(pending.effect_id) is None
            assert not app.host.gateway.port.session.backend.receipts
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id);restarted.client.start()
            assert not restarted.host.gateway.port.session.backend.receipts
            assert restarted.client.run_until_settled(run_id).status=='completed'
            NoActionFixture().assert_complete(restarted,plan,restarted.host.result(run_id),1,1)
            assert restarted.host.material.get(run_id)[2]==2
        finally:restarted.close()

    @pytest.mark.parametrize('point',['trailing_logical','group_checkpoint','unknown_physical','missing_physical'])
    def test_mixed_group_recovery_never_replays_physical_members(self,tmp_path,monkeypatch,point):
        source=f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let assay=plate(format="96well",capacity=200uL); assay[A1:A4] << [series(stock,[0uL,20uL,20uL,0uL])];'
        plan,context,app=PlateFixture().run_case(tmp_path,source,'p20_single_gen2')
        run_id,pending=NoActionFixture().pending(app,plan);ops=app.client.lifecycle.operations
        def crash(*args,**kwargs):raise KeyboardInterrupt('injected mixed group crash')
        if point=='trailing_logical':
            original=ops.logical.complete
            def on_last(identity,member,mode):
                if member.effect_id==pending.members[-1].effect_id:crash()
                return original(identity,member,mode)
            monkeypatch.setattr(ops.logical,'complete',on_last)
        elif point=='group_checkpoint':monkeypatch.setattr(ops.state,'mark_ready',crash)
        elif point=='missing_physical':
            # Crash after first physical receipt has been saved and registered.
            original_reconcile=ops.material.reconcile
            def after_registration(member,fact):
                result=original_reconcile(member,fact)
                if member.effect_id==pending.members[1].effect_id:crash()
                return result
            monkeypatch.setattr(ops.material,'reconcile',after_registration)
        else:
            monkeypatch.setattr(app.host.gateway.port.session.backend.pipette,'dispense',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('unknown dispense')))
        try:
            if point=='unknown_physical':ops.dispatch_ready(run_id)
            else:
                with pytest.raises(KeyboardInterrupt):ops.dispatch_ready(run_id)
            if point in {'unknown_physical','missing_physical'}:
                assert ops.evidence.find_logical_completion(pending.members[-1].effect_id) is None
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id);restarted.client.start()
            status=restarted.client.run_until_settled(run_id).status
            assert status==('needs_reconciliation' if point in {'unknown_physical','missing_physical'} else 'completed')
            assert not restarted.host.gateway.port.session.backend.receipts
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            if status=='completed':assert restarted.client.result(run_id).ok
            else:
                assert restarted.client.lifecycle.operations.resource.occupied()
                assert restarted.client.lifecycle.evidence.find_logical_completion(pending.members[-1].effect_id) is None
        finally:restarted.close()

    @pytest.mark.parametrize('point',['middle_member','group_checkpoint'])
    def test_all_logical_group_restart(self,tmp_path,monkeypatch,point):
        source=f'let stock=tube(capacity=2000uL,load=[{BUFFER}:200uL]); let assay=plate(format="96well",capacity=200uL); assay[A1:A4] << [stock:0uL];'
        plan,context,app=PlateFixture().run_case(tmp_path,source,'p20_single_gen2')
        run_id,pending=NoActionFixture().pending(app,plan);ops=app.client.lifecycle.operations
        def crash(*a,**k):raise KeyboardInterrupt('logical group restart')
        if point=='middle_member':
            original=ops.logical.complete
            def after_two(identity,member,mode):
                if member.effect_id==pending.members[2].effect_id:crash()
                return original(identity,member,mode)
            monkeypatch.setattr(ops.logical,'complete',after_two)
        else:monkeypatch.setattr(ops.state,'mark_ready',crash)
        try:
            with pytest.raises(KeyboardInterrupt):ops.dispatch_ready(run_id)
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id);restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status=='completed'
            NoActionFixture().assert_complete(restarted,plan,restarted.host.result(run_id),4,0)
            assert restarted.host.material.get(run_id)[2]==4
        finally:restarted.close()

    @pytest.mark.parametrize('body',[
        'target << [source:0uL] with constraint(gentle);',
        'with env(thermal=37C) { target << [source:0uL]; }',
        'target << [source:-1uL];',
    ])
    def test_constraints_and_invalid_quantities_are_not_skipped(self,tmp_path,body):
        plan,context,app=NoActionFixture().build(tmp_path,body)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert app.host.material.repository.connection.execute('SELECT count(*) FROM os_logical_completions').fetchone()[0]==0
        finally:app.close()

    def test_logical_and_physical_records_cannot_overlap(self,tmp_path):
        plan,context,app=NoActionFixture().build(tmp_path,'target << [source:0uL];')
        run_id,pending=NoActionFixture().pending(app,plan);ops=app.client.lifecycle.operations
        try:
            resolution=ops.logical.complete(run_id,pending,'simulation')
            assert ops.logical.complete(run_id,pending,'simulation')==resolution
            completion=ops.evidence.find_logical_completion(pending.effect_id)
            with pytest.raises(ValueError,match='LOGICAL_COMPLETION_CONFLICT'):
                ops.evidence.record_logical_completion(replace(completion,payload={'completion_kind':'logical','device_action':False,'different':True}))
            with pytest.raises(ValueError,match='LOGICAL_PHYSICAL_CONFLICT'):
                ops.evidence.repository.record_intent(AttemptRecord('a',run_id,pending.effect_id,'simulation',{}))
            other=replace(completion,effect_id='physical-first',completion_id='physical-first:logical')
            ops.evidence.repository.record_intent(AttemptRecord('b',run_id,'physical-first','simulation',{}))
            with pytest.raises(ValueError,match='LOGICAL_PHYSICAL_CONFLICT'):ops.evidence.record_logical_completion(other)
            forged=replace(completion,proposed_state_fingerprint='wrong')
            with pytest.raises(ValueError,match='MATERIAL_LOGICAL_COMPLETION_MISMATCH'):ops.material.reconcile_logical(pending,forged)
            state=deepcopy(pending.before_material_state['containers'])
            for container in state.values():container['component_quantities']={'unknown':{'status':'unknown','dimension':'mass','value':None}}
            assert not ops.transfer.is_empty_movement({'mode':'full','moved_uL':0,'moved_mg':0,'moved_cells':0},next(iter(state.values())))
            canonical_only={'component_entries':[{'amount':None,'quantity':{'status':'unknown','value':None}}]}
            assert not ops.transfer.is_empty_movement({'mode':'full','moved_uL':0,'moved_mg':0,'moved_cells':0},canonical_only)
            canonical_only['component_entries'][0]={'amount':10,'quantity':{'value':10}}
            assert not ops.transfer.is_empty_movement({'mode':'full','moved_uL':0,'moved_mg':0,'moved_cells':0},canonical_only)
        finally:app.close()

    def test_all_logical_multichannel_group_has_no_device_plan(self,tmp_path,monkeypatch):
        plan,context,app=MultichannelOSFixture().build(tmp_path,source=COLUMN_SOURCE.replace('stock:20uL','stock:0uL'))
        def forbidden(*a,**k):raise AssertionError('all-logical group reached device planner')
        monkeypatch.setattr(app.host.gateway,'prepare_collective_group',forbidden)
        try:
            result=app.execute(plan,init_state(plan))
            NoActionFixture().assert_complete(app,plan,result,8,0)
            assert not app.host.gateway.port.session.backend.protocol.commands()
        finally:app.close()

    def test_no_action_architecture(self):
        root=Path(__file__).resolve().parents[1]/'src/culsma_os'
        assert 'class LogicalEffectInteractor' in (root/'scheduler/interactors.py').read_text()
        assert 'class LogicalCompletion' in (root/'event_journal/models.py').read_text()
        material=(root/'material_system/interactors.py').read_text()
        assert 'reconcile_logical' in material and 'OS_TRANSFER_NO_ACTION' in material
        for relative in ['scheduler/interactors.py','transfer_engine/interactors.py','event_journal/interactors/evidence.py','material_system/interactors.py']:
            source=(root/relative).read_text()
            assert 'culsma_opentrons' not in source and 'culsma_driver_hamilton' not in source
        for node in ast.walk(ast.parse((root/'event_journal/models.py').read_text())):
            if isinstance(node,ast.ClassDef) and node.name=='LogicalCompletion':
                fields={n.target.id for n in node.body if isinstance(n,ast.AnnAssign)}
                assert not fields & {'attempt_id','consumed_resources','outcome'}

    @pytest.mark.parametrize('entry',['language','os'])
    def test_cli_no_action(self,tmp_path,entry):
        plan,context,app=NoActionFixture().build(tmp_path,'source << [source:50uL]; target << [source:0uL]; target << [source:50uL];')
        app.close()
        artifacts=tmp_path/'cli-output'
        command=[str(Path(sys.executable).parent/'culsma')] if entry=='language' else [sys.executable,'-m','culsma_os.cli']
        result=subprocess.run([*command,'run',str(tmp_path/'protocol.culs'),'--driver','opentrons-simulator','--driver-config',str(context.config_path),'--artifacts-dir',str(artifacts)],capture_output=True,text=True,cwd=tmp_path)
        assert result.returncode==0,result.stdout+result.stderr
        report=json.loads((artifacts/'run.json').read_text())
        assert report['user_result']['os']['status']=='completed'
        with sqlite3.connect(artifacts/'culsma-os.sqlite3') as conn:
            assert conn.execute('SELECT count(*) FROM os_logical_completions').fetchone()[0]==2
            assert conn.execute('SELECT count(*) FROM os_attempts').fetchone()[0]==1
