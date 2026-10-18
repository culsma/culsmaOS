"""Eight-channel shared physical effects through the hosted language path."""
from dataclasses import replace
import ast
from pathlib import Path
import sqlite3
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.material_system.models import MaterialCommitProposal
from culsma_os.material_system.repositories.local import LocalMaterialRepository
from tests.test_plate96 import PlateFixture, BUFFER
from tests.test_group_handoff import GroupFixture


SOURCE=f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:1000uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); assay[A1:H1] << [stock:20uL];'


class MultichannelOSFixture:
    def build(self, tmp_path, source=SOURCE, pipette='p20_multi_gen2', reservoir=True):
        fixture=PlateFixture();plan=fixture.compile(source,tmp_path)
        def configure(raw):
            raw['tiprack']['load_name']='opentrons_96_tiprack_20ul' if pipette.startswith('p20') else 'opentrons_96_tiprack_300ul'
            if reservoir: raw['labware']['tubes']['load_name']='nest_12_reservoir_15ml'
        context=fixture.context(tmp_path,plan,pipette,config_mutation=configure)
        return plan,context,OSApplicationFactory().build(context)


class TestMultichannelOS:
    @pytest.mark.parametrize('pipette',['p20_multi_gen2','p300_multi_gen2'])
    def test_os_column_matches_language_and_uses_one_wave(self,tmp_path,pipette):
        plan,context,app=MultichannelOSFixture().build(tmp_path,pipette=pipette)
        try:
            result=app.execute(plan,init_state(plan))
            assert result.ok,[d.to_dict() for d in result.diagnostics]
            assert result.state.artifacts['material_state']==run(plan,StubDriver()).state.artifacts['material_state']
            backend=app.host.gateway.port.session.backend
            assert len(backend.receipts)==1 and len(backend.receipts[0].operation.commands)==1
            assert backend.available_tips()==88
            run_id=result.user_result['os']['run_id']
            checkpoint=app.client.execution.host.codec.loads(app.client.get_run(run_id).checkpoint)
            resolution=checkpoint['confirmed'][0].resolution
            assert len(resolution.members)==8
            evidence=app.client.lifecycle.evidence
            shared=evidence.find_evidence(resolution.effect_id)
            assert shared.consumed_resources=={'tips':8}
            assert shared.payload['total_source_volume_uL']==160
            assert shared.payload['evidence_scope']=='shared_eight_channel_wave'
            facts=[evidence.find_evidence(m.effect_id) for m in resolution.members]
            assert all(f.payload['shared_evidence_id']==shared.evidence_id and f.consumed_resources=={} for f in facts)
            assert evidence.known_consumption('opentrons')=={'tips':8}
            assert not app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.device.get('opentrons').transfer_channels==8
            assert app.client.lifecycle.operations.material.get(run_id)[1]==result.state.artifacts['material_state']
        finally:app.close()

    @pytest.mark.parametrize('action',['aspirate','dispense','drop_tip'])
    def test_unknown_wave_marks_all_members_and_never_replays(self,tmp_path,monkeypatch,action):
        plan,context,app=MultichannelOSFixture().build(tmp_path)
        def fail(*args,**kwargs):raise RuntimeError('wave uncertainty')
        monkeypatch.setattr(app.host.gateway.port.session.backend.pipette,action,fail)
        run_id,pending=GroupFixture().pending(app,plan)
        try:
            record=app.client.run_until_settled(run_id)
            assert record.status=='needs_reconciliation'
            assert set(app.client.lifecycle.operations.material.uncertainties(run_id))=={m.effect_id for m in pending.members}
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.evidence.known_consumption('opentrons')=={'tips':8}
            assert all(app.client.lifecycle.evidence.find_evidence(m.effect_id).outcome=='unknown' for m in pending.members)
            containers=app.client.lifecycle.operations.material.get(run_id)[1]['containers'].values()
            assert sorted(c['volume_uL'] for c in containers)==[0]*8+[1000]
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.host.gateway.port.session.backend.available_tips()==88
            assert restarted.client.lifecycle.operations.resource.occupied()
        finally:restarted.close()

    @pytest.mark.parametrize('crash_point',['projection','registration','transaction','resume'])
    def test_saved_wave_recovers_without_device_execution(self,tmp_path,monkeypatch,crash_point):
        plan,context,app=MultichannelOSFixture().build(tmp_path)
        run_id,pending=GroupFixture().pending(app,plan)
        def crash(*args,**kwargs):raise KeyboardInterrupt('after shared evidence')
        if crash_point=='projection': monkeypatch.setattr(app.client.lifecycle.evidence,'project_collective_members',crash)
        if crash_point=='registration': monkeypatch.setattr(app.client.lifecycle.operations.material,'reconcile_collective_group',crash)
        if crash_point=='transaction':
            repository=app.client.lifecycle.operations.material.repository
            original=repository.commit_in_transaction
            calls=[]
            def fail_after_three(*args):
                calls.append(1)
                if len(calls)==4:raise KeyboardInterrupt('inside wave material transaction')
                return original(*args)
            monkeypatch.setattr(repository,'commit_in_transaction',fail_after_three)
        if crash_point=='resume': monkeypatch.setattr(app.client.lifecycle.operations.state,'mark_ready',crash)
        try:
            with pytest.raises(KeyboardInterrupt):app.client.lifecycle.operations.dispatch_ready(run_id)
            assert app.client.lifecycle.evidence.find_evidence(pending.effect_id).outcome=='completed'
            assert len(app.host.gateway.port.session.backend.receipts)==1
            if crash_point=='transaction':
                assert all(app.client.lifecycle.operations.material.repository.receipt(m.effect_id) is None for m in pending.members)
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status=='completed'
            assert restarted.client.result(run_id).ok
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.host.gateway.port.session.backend.available_tips()==88
            assert not restarted.client.lifecycle.operations.resource.occupied()
            # Idempotent recovery must not double-charge the wave.
            restarted.client.lifecycle.recovery.reconcile_unfinished_runs()
            assert restarted.client.lifecycle.evidence.known_consumption('opentrons')=={'tips':8}
        finally:restarted.close()

    def test_intent_without_wave_evidence_blocks_replay(self,tmp_path,monkeypatch):
        plan,context,app=MultichannelOSFixture().build(tmp_path)
        run_id,pending=GroupFixture().pending(app,plan)
        def crash(*args):raise KeyboardInterrupt('device returned before wave persisted')
        monkeypatch.setattr(app.client.lifecycle.evidence,'ingest',crash)
        try:
            with pytest.raises(KeyboardInterrupt):app.client.lifecycle.operations.dispatch_ready(run_id)
            assert len(app.host.gateway.port.session.backend.receipts)==1
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(run_id)
            restarted.client.start()
            assert restarted.client.run_until_settled(run_id).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.operations.resource.occupied()
        finally:restarted.close()

    @pytest.mark.parametrize('case',['tube','missing','horizontal','unequal','scalar'])
    def test_os_multichannel_rejects_before_actions(self,tmp_path,case):
        source=SOURCE
        if case=='missing': source=source.replace('A1:H1','A1:G1')
        if case=='horizontal': source=source.replace('A1:H1','A1:A8')
        if case=='unequal': source=source.replace('stock:20uL','series(stock,[20uL,10uL,20uL,20uL,20uL,20uL,20uL,20uL])')
        if case=='scalar': source=source.replace('A1:H1','A1:A1')
        plan,context,app=MultichannelOSFixture().build(tmp_path,source,reservoir=case!='tube')
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert not app.host.gateway.port.session.backend.protocol.commands()
            assert not app.client.lifecycle.operations.resource.occupied()
            assert any('DRV_OT_MULTICHANNEL' in d.message for d in result.diagnostics)
        finally:app.close()

    def test_collective_material_registration_is_atomic(self):
        connection=sqlite3.connect(':memory:')
        repository=LocalMaterialRepository(connection)
        repository.bind('run','simulation',{'quantity':1000})
        first=MaterialCommitProposal('a','ea',{'quantity':1000},{'quantity':980},'fa')
        invalid=MaterialCommitProposal('b','eb',{'quantity':999},{'quantity':960},'fb')
        with pytest.raises(ValueError):repository.commit_group_once('run','simulation',(first,invalid))
        assert repository.get('run')==('simulation',{'quantity':1000},0)
        assert repository.receipt('a') is None
        second=replace(invalid,before={'quantity':980})
        receipts=repository.commit_group_once('run','simulation',(first,second))
        assert repository.get('run')==('simulation',{'quantity':960},2)
        assert repository.commit_group_once('run','simulation',(first,second))==receipts
        connection.close()

    def test_collective_boundaries(self):
        root=Path(__file__).resolve().parents[1]/'src/culsma_os'
        for name in ['scheduler/interactors.py','transfer_engine/interactors.py','driver_framework/interactors.py']:
            text=(root/name).read_text()
            assert 'culsma_opentrons' not in text and 'pick_up_tip' not in text
        adapter=(root/'driver_framework/adapters/opentrons.py').read_text()
        assert '.backend' not in adapter and '.pipette' not in adapter
        assert not any('Repository' in alias.name for node in ast.walk(ast.parse(adapter)) if isinstance(node,ast.ImportFrom) for alias in node.names)
