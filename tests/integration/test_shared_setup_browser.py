import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_MCP_SDK_PATH','CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME']),
    reason='Optional browser and official MCP SDK test environments are required')
def test_browser_observes_real_mcp_edits_and_operator_confirms_loading(tmp_path,monkeypatch):
    import culsma_driver_hamilton
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    artifacts=ROOT/'run-artifacts/ui-tests'
    artifacts.mkdir(parents=True,exist_ok=True)
    with SharedSetupHarness(tmp_path) as shared:
        env={**os.environ,'CULSMA_OS_TEST_PYTHON':sys.executable}
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/setup_browser.mjs'),
            shared.url,shared.run_id,str(shared.endpoint),str(artifacts/'run-setup.png'),
            str(ROOT/'tests/modules/console/goldens/run-setup-1280.png')],env=env,capture_output=True,text=True,timeout=60,cwd=ROOT)
        assert result.returncode==0,result.stderr
        shared.wait(lambda:shared.status(shared.run_id)['status']=='completed')
        assert len(shared.backend.calls)==2
