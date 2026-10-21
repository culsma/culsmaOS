"""Existing OS pipeline with an external Hamilton plugin and labelled execution doubles."""
from pathlib import Path
import json
import os
import socket
import subprocess
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.program_manager.interactors.compilation import CompilationInteractor


class HamiltonOperationTestBackend:
    def __init__(self, outcome='completed'):
        self.outcome, self.calls = outcome, []
    def build(self, configuration): return self
    def validate(self, plan): pass
    def check_ready(self): pass
    def close(self): pass
    def execute(self, plan, attempt_id):
        from culsma_driver_hamilton.device_models import HamiltonOperationOutcome
        self.calls.append((plan,attempt_id))
        return HamiltonOperationOutcome(self.outcome,{'source':'test-double','vendor_simulation':False},
            plan.tip_count if self.outcome=='completed' else 0)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    vendor=pytest.importorskip('culsma_driver_hamilton')
    driver=Path(vendor.__file__).resolve().parents[2]
    labware=Path(os.environ.get('CULSMA_HAMILTON_LABWARE_ROOT', driver/'reference/LabWare'))
    if not (labware/'ML_STAR/CORE/VStarWaste_8Pos.rck').is_file():
        pytest.skip('Optional local Hamilton definitions unavailable')
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(labware))
    def forbidden(*args,**kwargs): pytest.fail('Local contract test attempted network or process launch')
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    example=driver/'examples/os-transfer-input'
    source=tmp_path/'transfer.culs';source.write_text((example/'transfer.culs').read_text())
    original=json.loads((example/'setup.json').read_text())
    configuration={'schema':'culsma_hamilton_device_v1','device_id':'hamilton-contract-test','mode':'simulation',
        'layout':original['layout'],'execution':original['execution'],
        'bindings':{key:{'labware':value['labware'],'well':value.get('position','1')} for key,value in original['bindings'].items()},
        'well_positions':{},'agent':{}}
    config=tmp_path/'device.json';config.write_text(json.dumps(configuration))
    compiled=CompilationInteractor().compile([source])
    return compiled,HostBuildContext(tmp_path/'os.sqlite3','hamilton-agent',config,tmp_path/'artifacts')


def test_original_os_pipeline_executes_two_transfers_through_external_device_port(fixture,monkeypatch):
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
    compiled,context=fixture
    backend=HamiltonOperationTestBackend()
    factory=HamiltonOSDeviceFactory(backend_factory=backend)
    class Entry:
        def load(self): return lambda:factory
    import culsma_os.bootstrap as composition
    calls=[]
    def entries(**kwargs):
        calls.append(kwargs)
        return [Entry()]
    monkeypatch.setattr(composition,'entry_points',entries)
    app=OSApplicationFactory(session_factories={}).build(context)
    try:
        assert callable(app.host.gateway.port.prepare) and callable(app.host.gateway.port.execute)
        result=app.execute(compiled.plan,compiled.state)
        assert result.ok, result.diagnostics
        assert calls==[{'group':'culsma.os_devices','name':'hamilton-agent'}]
        assert len(backend.calls)==2
        assert [plan.intent.aliquots[0].volume_uL for plan,_ in backend.calls]==[50,50]
        assert len({attempt for _,attempt in backend.calls})==2
        run_id=result.user_result['os']['run_id']
        attempts=app.client.lifecycle.evidence.attempts_for_run(run_id)
        assert len(attempts)==2
        assert all(app.client.lifecycle.evidence.find_evidence(a.effect_id).outcome=='completed' for a in attempts)
        assert sorted(c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values())==[100,100]
        assert app.host.material.get(run_id)[2]==2
        assert not app.client.lifecycle.operations.resource.occupied()
        assert [plan.start_tip_index for plan,_ in backend.calls]==[0,1]
    finally: app.close()


def test_unknown_remote_operation_uses_original_isolation_and_blocks_next_transfer(fixture):
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
    compiled,context=fixture
    backend=HamiltonOperationTestBackend('unknown')
    app=OSApplicationFactory(session_factories={'hamilton-agent':HamiltonOSDeviceFactory(backend_factory=backend)}).build(context)
    try:
        result=app.execute(compiled.plan,compiled.state)
        assert not result.ok
        run_id=result.user_result['os']['run_id']
        assert app.client.get_run(run_id).status=='needs_reconciliation'
        assert len(backend.calls)==1
        assert app.client.lifecycle.operations.resource.occupied()
        assert app.host.gateway.port.next_tip_index==0
        _, material, version=app.host.material.get(run_id)
        assert version==0
        assert sorted(c['volume_uL'] for c in material['containers'].values())==[0,200]
    finally: app.close()


def test_original_language_cli_routes_through_installed_hamilton_os_entries(fixture,monkeypatch,tmp_path,capsys):
    import sys
    from culsma import cli
    from culsma_hamilton_os.providers import HamiltonAgentBackendFactory
    _,context=fixture
    backend=HamiltonOperationTestBackend()
    monkeypatch.setattr(HamiltonAgentBackendFactory,'build',lambda self,configuration:backend)
    source=context.config_path.parent/'transfer.culs'
    monkeypatch.setattr(sys,'argv',['culsma','run',str(source),'--driver','hamilton-agent',
        '--driver-config',str(context.config_path),'--artifacts-dir',str(tmp_path/'cli-artifacts'),'--json'])
    cli.main()
    output=json.loads(capsys.readouterr().out)
    assert output['report']['os']['status']=='completed'
    assert len(backend.calls)==2


def test_transfer_session_does_not_advertise_unimplemented_processing(fixture):
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
    _, context = fixture
    port, snapshot, _, _, _ = HamiltonOSDeviceFactory(
        backend_factory=HamiltonOperationTestBackend()).build(context)
    try:
        assert snapshot.supports_transfer is True
        assert snapshot.processing_capabilities == {}
        assert snapshot.motion_capabilities == {}
        assert snapshot.feedback_capabilities.completion_units == ('operation',)
    finally:
        port.close()


@pytest.mark.parametrize('operation', [
    'Incubate(sample=destination,temp=37C,duration=30s);',
    'agit(sample=destination,mode=centrifuge,drive=500g,duration=30s);',
])
def test_unsupported_processing_is_rejected_before_any_hamilton_transfer(fixture, operation):
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
    _, context = fixture
    source = context.config_path.parent / 'transfer.culs'
    source.write_text(source.read_text() + '\n' + operation)
    compiled = CompilationInteractor().compile([source])
    backend = HamiltonOperationTestBackend()
    app = OSApplicationFactory(session_factories={
        'hamilton-agent': HamiltonOSDeviceFactory(backend_factory=backend)}).build(context)
    try:
        result = app.execute(compiled.plan, compiled.state)
        assert not result.ok
        assert not backend.calls
        assert app.host.gateway.port.next_tip_index == 0
    finally:
        app.close()
