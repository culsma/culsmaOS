from tests.support.paths import ROOT
import ast
from pathlib import Path
import json
import subprocess
import sys
from dataclasses import replace
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
from tests.support.processing_engine.processing_magnetic import DECLARATIONS, MAGNETIC, SOURCE, MagneticFixture


class TestMagneticProcessing:
    @pytest.mark.parametrize('selection',['40uL','all','20uL-repeat','zero'])
    def test_separate_and_transfer(self,tmp_path,selection):
        source=SOURCE
        if selection=='zero':source=source.replace(':40uL',':0uL')
        if selection=='all':source=source.replace(':40uL','')
        if selection=='20uL-repeat':source=source.replace('waste << [sample.contents[1]:40uL];','waste << [sample.contents[1]:20uL]; waste << [sample.contents[1]:20uL];')
        plan,context,app=MagneticFixture().build(tmp_path,source)
        try:
            result=app.execute(plan,init_state(plan))
            identity=MagneticFixture().compare(app,plan,result)
            session=app.host.gateway.port.session
            assert len(session.magnetic.receipts)==2
            assert session.magnetic.receipts[0].payload['phases']=={'engage':'returned','wait':'returned'}
            assert session.magnetic.receipts[1].payload['phases']=={'disengage':'returned'}
            assert not session.magnetic.held
            assert session.backend.protocol.commands()[-1]=='Disengaging Magnetic Module'
            containers=result.state.artifacts['material_state']['containers']
            sample=next(v for v in containers.values() if v['metadata']['kind']=='well')
            assert sample['components']['BEADS']==10
            assert sample['components']['BUFFER']==(0 if selection=='all' else 80 if selection=='zero' else 40)
            assert app.host.material.get(identity)[2]==(4 if selection=='20uL-repeat' else 3)
            attempts=app.client.lifecycle.evidence.attempts_for_run(identity)
            releases=[a for a in attempts if a.context['description'].get('system_effect')=='condition_release']
            assert len(releases)==1 and not app.host.material.registered(releases[0].effect_id)
            conditions = app.client.lifecycle.conditions
            assert conditions.is_release_attempt(releases[0])
            assert not conditions.is_release_attempt(replace(releases[0], run_id='unrelated-run'))
            assert not conditions.is_release_attempt(replace(releases[0], effect_id='unrelated-effect'))
        finally:app.close()

    @pytest.mark.parametrize('kind',['bound','other-program','no-duration','extra-duration','no-field','no-hold-target','collateral','no-module','whole-source','source-partition'])
    def test_rejects_unsupported_scope(self,tmp_path,kind):
        source=SOURCE;configure=None
        if kind=='bound':source=source.replace('contents[1]','contents[0]').replace(':40uL',':5uL')
        if kind=='other-program':source=source.replace('magnetic_program(duration=5min)','centrifuge_program(drive=1000g)')
        if kind=='no-duration':source=source.replace('duration=5min','')
        if kind=='extra-duration':source=source.replace('field=magnetic_rack','field=magnetic_rack,thermal=37C,duration=10min')
        if kind=='no-field':source=DECLARATIONS+'sample << [stock];sep(sample=sample,program=magnetic_program(duration=5min));waste << [sample.contents[1]:40uL];'
        if kind=='no-hold-target':source=source.replace('hold(sample=sample);','')
        if kind=='collateral':source=source.replace('let w=p[A1];','let other=p[B1];let w=p[A1];')
        if kind=='whole-source':source=source.replace('sample.contents[1]','sample')
        if kind=='source-partition':source=source.replace('sample.contents[1]','sample.partition(magnetic_program(duration=5min))[1]')
        if kind=='no-module':
            def configure(raw):
                raw.pop('modules');raw['labware']['assay']={'load_name':'nest_96_wellplate_100ul_pcr_full_skirt','slot':'6'}
        plan,context,app=MagneticFixture().build(tmp_path,source,configure)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok
            assert not any('Aspirating 40.0' in c for c in app.host.gateway.port.session.backend.protocol.commands())
            assert app.client.get_run(result.user_result['os']['run_id']).status in {'failed','needs_reconciliation'}
        finally:app.close()

    @pytest.mark.parametrize('phase,method',[('engage','engage'),('wait','delay')])
    def test_unknown_retains_reservation(self,tmp_path,monkeypatch,phase,method):
        plan,context,app=MagneticFixture().build(tmp_path)
        identity,pending=MagneticFixture().waiting_separation(app,plan)
        session=app.host.gateway.port.session
        obj=session.backend.protocol if method=='delay' else session.backend.modules['magnet']
        def fail(*a,**k):raise RuntimeError('uncertain magnetic phase')
        monkeypatch.setattr(obj,method,fail)
        try:
            app.client.lifecycle.operations.dispatch_ready(identity)
            assert app.client.get_run(identity).status=='needs_reconciliation'
            assert len(session.backend.receipts)==1
            assert session.magnetic.receipts[0].outcome=='unknown'
            assert app.client.lifecycle.reservations.get(identity).status=='active'
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.host.material.get(identity)[2]==1
        finally:app.close()

    def test_release_failure_retains_reservation(self,tmp_path,monkeypatch):
        plan,context,app=MagneticFixture().build(tmp_path)
        def fail(*a,**k):raise RuntimeError('uncertain release')
        monkeypatch.setattr(app.host.gateway.port.session.backend.modules['magnet'],'disengage',fail)
        try:
            result=app.execute(plan,init_state(plan));identity=result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status']=='needs_reconciliation'
            assert app.host.material.get(identity)[2]==3
            assert app.client.lifecycle.reservations.get(identity).status=='active'
            assert app.client.lifecycle.operations.resource.occupied()
            assert app.client.lifecycle.reservations.safety.release_proof(identity) is None
        finally:app.close()

    @pytest.mark.parametrize('point',['registration','checkpoint','missing-feedback'])
    def test_recovery_does_not_reengage(self,tmp_path,monkeypatch,point):
        plan,context,app=MagneticFixture().build(tmp_path)
        identity,pending=MagneticFixture().waiting_separation(app,plan)
        ops=app.client.lifecycle.operations
        def crash(*a,**k):raise KeyboardInterrupt('magnetic interruption')
        obj,method=(ops.material,'reconcile') if point=='registration' else (ops.state,'mark_ready') if point=='checkpoint' else (app.host.gateway,'execute')
        monkeypatch.setattr(obj,method,crash)
        try:
            with pytest.raises(KeyboardInterrupt):ops.dispatch_ready(identity)
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            record=restarted.client.run_until_settled(identity)
            assert record.status in {'failed','needs_reconciliation'}
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.reservations.get(identity).status=='active'
        finally:restarted.close()

    def test_completed_release_is_not_replayed(self,tmp_path,monkeypatch):
        plan,context,app=MagneticFixture().build(tmp_path)
        lifecycle=app.client.lifecycle
        original=lifecycle.operations.resource.settle
        def crash(attempt_id,evidence):
            if evidence.payload.get('operation_kind')=='magnetic_release':raise KeyboardInterrupt('after release evidence')
            return original(attempt_id,evidence)
        monkeypatch.setattr(lifecycle.operations.resource,'settle',crash)
        try:
            with pytest.raises(KeyboardInterrupt):app.execute(plan,init_state(plan))
            identity=next(iter(lifecycle.runs.session_runs))
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='completed'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.reservations.get(identity).status=='released'
            assert not restarted.client.lifecycle.operations.resource.occupied()
        finally:restarted.close()

    @pytest.mark.parametrize('entry',['os','language'])
    def test_cli_magnetic(self,tmp_path,entry):
        plan,context,app=MagneticFixture().build(tmp_path);app.close()
        artifacts=tmp_path/'cli-artifacts'
        result=subprocess.run([sys.executable,'-m','culsma_os.cli' if entry=='os' else 'culsma.cli','run',str(tmp_path/'protocol.culs'),
            '--driver','opentrons-simulator','--driver-config',str(context.config_path),'--artifacts-dir',str(artifacts)],capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        data=json.loads((artifacts/'run.json').read_text())
        assert data['ok'] and data['user_result']['os']['status']=='completed'

    def test_architecture_boundaries(self):
        root=ROOT/'src/culsma_os'
        assert 'magnetic' not in (root/'scheduler/interactors.py').read_text().lower()
        adapter=(root/'driver_framework/adapters/opentrons.py').read_text()
        assert '.engage(' not in adapter and '.disengage(' not in adapter
        for path in (root/'processing_engine').rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):
                    assert not (node.module or '').startswith('culsma_opentrons')
                    assert not any(a.name.endswith('Repository') for a in node.names)
        assert not (root/'processing_engine/repository.py').exists()


    def test_field_is_retained_across_steps(self,tmp_path):
        plan,context,app=MagneticFixture().build(tmp_path)
        identity,pending=MagneticFixture().waiting_separation(app,plan)
        try:
            ops=app.client.lifecycle.operations
            ops.dispatch_ready(identity)
            assert app.client.get_run(identity).status=='ready'
            assert app.client.lifecycle.reservations.get(identity).status=='active'
            assert not ops.resource.occupied()
            assert 'magnet' in app.host.gateway.port.session.magnetic.held
            assert app.client.lifecycle.conditions.outstanding(identity)
            assert app.client.lifecycle.reservations.safety.release_proof(identity) is None
            assert app.client.pause_run(identity).status=='paused'
            assert app.client.run_until_settled(identity).status=='paused'
            assert len(app.host.gateway.port.session.magnetic.receipts)==1
            app.client.resume_run(identity)
            assert app.client.run_until_settled(identity).status=='completed'
            assert not app.client.lifecycle.conditions.outstanding(identity)
        finally:app.close()

    @pytest.mark.parametrize('point',['before-execute','after-physical-release'])
    def test_missing_release_feedback_is_never_replayed(self,tmp_path,monkeypatch,point):
        plan,context,app=MagneticFixture().build(tmp_path)
        session=app.host.gateway.port.session
        original=app.host.gateway.execute
        def crash(plan,permit,attempt_id):
            if plan.description.get('system_effect')=='condition_release':
                if point=='after-physical-release':original(plan,permit,attempt_id)
                raise KeyboardInterrupt('release feedback missing')
            return original(plan,permit,attempt_id)
        monkeypatch.setattr(app.host.gateway,'execute',crash)
        try:
            with pytest.raises(KeyboardInterrupt):app.execute(plan,init_state(plan))
            identity=next(iter(app.client.lifecycle.runs.session_runs))
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            record=restarted.client.run_until_settled(identity)
            assert record.status=='needs_reconciliation'
            assert restarted.client.lifecycle.reservations.get(identity).status=='active'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.reservations.safety.release_proof(identity) is None
        finally:restarted.close()


    def test_unknown_part_is_not_a_zero_action(self,tmp_path):
        from copy import deepcopy
        from culsma_os.transfer_engine.interactors import MagneticTransferInteractor
        plan,context,app=MagneticFixture().build(tmp_path)
        identity,pending=MagneticFixture().waiting_separation(app,plan)
        try:
            app.client.lifecycle.operations.dispatch_ready(identity)
            app.client.lifecycle.runs.advance_ready(identity)
            pending=app.client.execution.pending(identity)
            material=deepcopy(pending.before_material_state)
            source=next(iter(material['contents_states']))
            part=material['contents_states'][source]['parts']['1']
            part['component_quantities']['BUFFER']['status']='unknown'
            part['component_quantities']['BUFFER']['value']=None
            with pytest.raises(ValueError,match='TRANSFER_MAGNETIC_LIQUID_REQUIRED'):
                MagneticTransferInteractor().resolve_execution(replace(pending,before_material_state=material))
            assert not app.host.gateway.port.session.backend.module_action_results
        finally:app.close()

