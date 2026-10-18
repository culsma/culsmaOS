"""Complete static bead-buffer exchange, with repeated condition ownership."""
from pathlib import Path
import json,subprocess,sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from .test_processing_magnetic import MagneticFixture
from .test_flex_workstation import WorkstationDeviceFault

EXAMPLE=Path(__file__).resolve().parents[1]/'examples/magnetic-buffer-exchange'


class BufferExchangeFixture:
    def build(self,directory):
        return MagneticFixture().build(directory,(EXAMPLE/'protocol.culs').read_text())

    def complete(self,app,plan,result):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan,StubDriver(),init_state(plan));assert baseline.ok
        assert result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs']==baseline.state.artifacts['protocol_outputs']
        identity=result.user_result['os']['run_id'];session=app.host.gateway.port.session
        containers=result.state.artifacts['material_state']['containers']
        assert [c['volume_uL'] for c in containers.values()]==[10,0,240,240]
        waste=list(containers.values())[-1]
        assert waste['components']=={'BEADS':0,'STORAGE_BUFFER':80,'WASH_BUFFER':160}
        assert app.host.material.get(identity)[2]==9
        assert len(app.client.lifecycle.evidence.attempts_for_run(identity))==12
        assert app.client.lifecycle.reservations.get(identity).status=='released'
        assert not app.client.lifecycle.operations.resource.occupied()
        assert not session.magnetic.held
        assert session.backend.available_tips()==90
        return identity


class TestBufferExchange:
    def test_complete_protocol(self,tmp_path):
        plan,context,app=BufferExchangeFixture().build(tmp_path)
        try:
            assert (tmp_path/'protocol.culs').read_bytes()==(EXAMPLE/'protocol.culs').read_bytes()
            assert json.loads(context.config_path.read_text())==json.loads((EXAMPLE/'deck.json').read_text())
            result=app.execute(plan,init_state(plan));BufferExchangeFixture().complete(app,plan,result)
            receipts=app.host.gateway.port.session.magnetic.receipts
            assert [r.payload['operation_kind'] for r in receipts]==['magnetic_separation','magnetic_release']*3
            assert all(r.outcome=='completed' for r in receipts)
            assert [r.payload['request']['duration_seconds'] for r in receipts[::2]]==[120]*3
        finally:app.close()

    def test_missing_field_capability_rejects_before_actions(self,tmp_path):
        def configure(raw):
            raw['modules']['magnet']={'model':'temperature module gen2','slot':'6'}
        plan,_,app=MagneticFixture().build(tmp_path,(EXAMPLE/'protocol.culs').read_text(),configure)
        try:
            result=app.execute(plan,init_state(plan))
            assert not result.ok and result.user_result['os']['status']=='failed'
            assert 'PROCESSING_MODULE_UNAVAILABLE' in ' '.join(d.message for d in result.diagnostics)
            assert result.user_result['os']['preflight']['status']=='rejected'
            assert not app.host.gateway.port.session.backend.protocol.commands()
            identity=result.user_result['os']['run_id']
            assert not app.client.lifecycle.evidence.attempts_for_run(identity)
            assert not app.client.lifecycle.operations.resource.occupied()
            assert 'registered_material' not in result.user_result['os']
        finally:app.close()

    def test_release_precedes_each_wash(self,tmp_path,monkeypatch):
        plan,_,app=BufferExchangeFixture().build(tmp_path);session=app.host.gateway.port.session
        original=session.backend.pipette.aspirate;observations=[]
        def observe(*args,**kwargs):
            identity=next(iter(app.client.lifecycle.runs.session_runs))
            parent=app.client.lifecycle.reservations.get(identity).status
            assert parent=='active'
            observations.append((bool(session.magnetic.held),parent))
            return original(*args,**kwargs)
        monkeypatch.setattr(session.backend.pipette,'aspirate',observe)
        try:
            result=app.execute(plan,init_state(plan));identity=BufferExchangeFixture().complete(app,plan,result)
            assert [x[0] for x in observations]==[False,True,False,True,False,True]
            commands=session.backend.protocol.commands()
            release=[i for i,c in enumerate(commands) if c=='Disengaging Magnetic Module']
            wash=[i for i,c in enumerate(commands) if 'Aspirating' in c and 'A2 of' in c]
            assert len(wash)==2 and release[0]<wash[0]<release[1]<wash[1]<release[2]
            conditions=app.client.lifecycle.conditions
            for activation in conditions.activations(identity):
                assert conditions.release_completed(activation)
                assert not app.host.material.registered(conditions.release_id(activation))
        finally:app.close()

    @pytest.mark.parametrize('method,hit',[('engage',2),('delay',2),('disengage',1),('disengage',2),('disengage',3),('aspirate',4)])
    @pytest.mark.parametrize('after',[False,True])
    def test_unknown_stops_later_washes(self,tmp_path,monkeypatch,method,hit,after):
        plan,context,app=BufferExchangeFixture().build(tmp_path);session=app.host.gateway.port.session
        owner=session.backend.protocol if method=='delay' else session.backend.pipette if method=='aspirate' else session.backend.modules['magnet']
        fault=WorkstationDeviceFault(getattr(owner,method),hit,after);monkeypatch.setattr(owner,method,fault)
        try:
            result=app.execute(plan,init_state(plan));identity=result.user_result['os']['run_id']
            assert not result.ok and result.user_result['os']['status']=='needs_reconciliation'
            assert fault.calls==hit
            assert app.client.lifecycle.reservations.get(identity).status=='active'
            assert app.client.lifecycle.operations.resource.occupied()
            if method=='disengage':
                assert app.host.material.get(identity)[2]==[3,6,9][hit-1]
                assert len(session.backend.receipts)==[2,4,6][hit-1]
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='needs_reconciliation'
            assert restarted.client.lifecycle.reservations.get(identity).status=='active'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
        finally:restarted.close()

    def test_completed_midrun_release_recovers_without_replay(self,tmp_path,monkeypatch):
        plan,context,app=BufferExchangeFixture().build(tmp_path);resource=app.client.lifecycle.operations.resource
        original=resource.settle
        def crash(attempt_id,evidence):
            if evidence.payload.get('operation_kind')=='magnetic_release':
                raise KeyboardInterrupt('crash after durable midrun release receipt')
            return original(attempt_id,evidence)
        monkeypatch.setattr(resource,'settle',crash)
        try:
            with pytest.raises(KeyboardInterrupt):app.execute(plan,init_state(plan))
            identity=next(iter(app.client.lifecycle.runs.session_runs))
            assert len(app.host.gateway.port.session.magnetic.receipts)==2
        finally:app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            result=restarted.client.run_until_settled(identity)
            assert result.status=='completed'
            BufferExchangeFixture().complete(restarted,plan,restarted.host.result(identity))
            session=restarted.host.gateway.port.session
            assert len(session.magnetic.receipts)==4
            assert session.backend.protocol.commands().count('Engaging Magnetic Module')==2
            assert session.backend.protocol.commands().count('Disengaging Magnetic Module')==2
        finally:restarted.close()

    def test_missing_live_witness_never_reengages(self,tmp_path):
        plan,context,app=BufferExchangeFixture().build(tmp_path)
        identity,_=MagneticFixture().waiting_separation(app,plan)
        app.client.lifecycle.operations.dispatch_ready(identity)
        app.client.lifecycle.runs.advance_ready(identity)
        app.close()
        restarted=OSApplicationFactory().build(context)
        try:
            restarted.client.take_over_run(identity);restarted.client.start()
            assert restarted.client.run_until_settled(identity).status=='needs_reconciliation'
            assert not restarted.host.gateway.port.session.backend.protocol.commands()
            assert restarted.client.lifecycle.reservations.get(identity).status=='active'
        finally:restarted.close()

    def test_flowthrough_constraint_reaches_driver(self,tmp_path):
        plan,_,app=BufferExchangeFixture().build(tmp_path)
        try:
            result=app.execute(plan,init_state(plan));BufferExchangeFixture().complete(app,plan,result)
            receipts=app.host.gateway.port.session.backend.receipts
            for receipt in receipts[1::2]:
                applied=receipt.to_payload()['constraint_resolution']
                assert len(applied)==1 and applied[0]['requirement']=='low_carryover'
                assert applied[0]['method_id']=='fresh-tip-per-stroke'
        finally:app.close()

    @pytest.mark.parametrize('entry',['os','language'])
    def test_cli_entries(self,tmp_path,entry):
        plan,context,app=BufferExchangeFixture().build(tmp_path);app.close()
        artifacts=tmp_path/'cli'
        completed=subprocess.run([sys.executable,'-m','culsma_os.cli' if entry=='os' else 'culsma.cli','run',
            str(tmp_path/'protocol.culs'),'--driver','opentrons-simulator','--driver-config',str(context.config_path),
            '--artifacts-dir',str(artifacts)],capture_output=True,text=True)
        assert completed.returncode==0,completed.stdout+completed.stderr
        result=json.loads((artifacts/'run.json').read_text())
        assert result['ok'] and result['user_result']['os']['status']=='completed'
