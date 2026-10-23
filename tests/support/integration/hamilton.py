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


class HamiltonSetupFixture:
    @staticmethod
    def execute(app, compiled):
        from culsma_os.program_manager.models import RunRequest
        app.client.start()
        run_id = app.client.submit_run(RunRequest(compiled.plan, compiled.state))
        plan = app.client.setup_plan(run_id)
        app.client.begin_setup(run_id, plan['fingerprint'])
        app.client.confirm_setup(run_id, plan['fingerprint'], acknowledged=True, source='simulation_fixture')
        app.client.run_until_settled(run_id)
        return app.client.result(run_id)


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
