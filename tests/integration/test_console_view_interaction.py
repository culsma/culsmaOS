"""Real MCP subprocess → station-local records → real browser → render receipt."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME','CULSMA_OS_MCP_SDK_PATH']),reason='Explicit browser and optional MCP SDK required')
def test_mcp_view_requests_reach_browser_without_executing_experiment(tmp_path,monkeypatch):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    output=ROOT/'run-artifacts/ui-tests';output.mkdir(parents=True,exist_ok=True)
    with SharedSetupHarness(tmp_path) as shared:
        code,_,station=shared.http.request('GET','/api/v1/station')
        assert code==200
        entities=shared.http.server.view_requests.layout_entities(station['data']['layout'])
        entity='source_vessel' if 'source_vessel' in entities else sorted(entities)[0]
        result=subprocess.run([os.environ['CULSMA_OS_NODE'],str(ROOT/'tests/support/console/view_interaction_browser.mjs'),
            shared.url,str(shared.endpoint),shared.run_id,entity,sys.executable,str(output/'view-reveal-1280.png'),
            str(ROOT/'tests/modules/console/goldens/view-reveal-1280.png')],cwd=ROOT,env=os.environ,
            text=True,capture_output=True,timeout=100)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['business_writes']==0
        assert shared.status(shared.run_id)['status']=='awaiting_setup'
        assert not shared.backend.calls
