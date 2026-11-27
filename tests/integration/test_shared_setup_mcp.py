import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not os.environ.get('CULSMA_OS_MCP_SDK_PATH'),reason='Official MCP SDK runs in an isolated optional bridge environment')
def test_real_mcp_stdio_preparation_and_confirmation_share_console_state(tmp_path,monkeypatch):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_PRIVATE_LABWARE',str(driver/'reference/LabWare'))
    with SharedSetupHarness(tmp_path, submit=False) as shared:
        preparation=shared.client.execute({'action':'prepare','source':str(shared.source),'request_id':'mcp-preparation'})
        shared.run_id=preparation['run_id']
        assert preparation['status']=='awaiting_setup'
        assert not shared.backend.calls
        repeated=shared.client.execute({'action':'prepare','source':str(shared.source),'request_id':'mcp-preparation'})
        assert repeated['run_id']==shared.run_id
        assert not shared.backend.calls
        env={**os.environ,'PYTHONPATH':os.environ['CULSMA_OS_MCP_SDK_PATH']+os.pathsep+str(ROOT/'src')+os.pathsep+str(driver/'src')}
        result=subprocess.run([sys.executable,'-m','tests.support.console.mcp_client',str(shared.endpoint),shared.run_id,'--confirm'],
            env=env,capture_output=True,text=True,timeout=30,cwd=ROOT)
        assert result.returncode==0,result.stderr
        status,_,body=shared.http.request('POST','/api/v1/setup',shared.headers,{'action':'show','run_id':shared.run_id})
        assert status==200
        plan=body['data']
        assert any(e['origin']=='local-mcp-process' and e['action']=='revise' and e['status']=='completed' for e in plan['activity'])
        assert plan['confirmation']['physical_observation'] is False
        assert any(e['origin']=='local-mcp-process' and e['action']=='confirm' and e['status']=='completed' for e in plan['activity'])
        shared.wait(lambda:shared.status(shared.run_id)['status']=='completed')
        assert len(shared.backend.calls)==2
