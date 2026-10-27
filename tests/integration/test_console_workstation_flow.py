"""One Workstation presents the existing program/loading/execution use cases."""
import json
import os
from pathlib import Path
import subprocess
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME']), reason='Explicit local browser environment required')
def test_workstation_selects_prepares_executes_and_reviews_without_replay(tmp_path, monkeypatch):
    import culsma_driver_hamilton
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    (ROOT/'run-artifacts/ui-tests').mkdir(parents=True,exist_ok=True)
    with SharedSetupHarness(tmp_path,submit=False,programs=True) as shared:
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/workstation_flow_browser.mjs'),
            shared.url],capture_output=True,text=True,timeout=60,cwd=ROOT)
        assert result.returncode==0,result.stderr
        outcome=json.loads(result.stdout)
        assert outcome['commands']==['submit','begin','confirm']
        assert shared.status(outcome['run_id'])['status']=='completed'
        assert len(shared.client.execute({'action':'runs'})['runs'])==1
        assert len(shared.backend.calls)==2
