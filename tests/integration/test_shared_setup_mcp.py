import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not os.environ.get('CULSMA_OS_MCP_SDK_PATH'),reason='Official MCP SDK runs in an isolated optional bridge environment')
def test_real_mcp_stdio_edits_are_visible_in_console_and_cannot_confirm(tmp_path,monkeypatch):
    import culsma_driver_hamilton
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    with SharedSetupHarness(tmp_path) as shared:
        env={**os.environ,'PYTHONPATH':os.environ['CULSMA_OS_MCP_SDK_PATH']+os.pathsep+str(ROOT/'src')}
        result=subprocess.run([sys.executable,'-m','tests.support.console.mcp_client',str(shared.endpoint),shared.run_id],
            env=env,capture_output=True,text=True,timeout=30,cwd=ROOT)
        assert result.returncode==0,result.stderr
        status,_,body=shared.http.request('POST','/api/v1/setup',shared.headers,{'action':'show','run_id':shared.run_id})
        assert status==200
        plan=body['data']
        assert any(e['origin']=='local-mcp-process' and e['action']=='revise' and e['status']=='completed' for e in plan['activity'])
        assert plan['confirmation'] is None and not shared.backend.calls
        for action in ['begin','confirm']:
            request_id='console-'+action
            payload={'action':action,'run_id':shared.run_id,'fingerprint':plan['fingerprint'],'request_id':request_id}
            if action=='confirm': payload['acknowledged']=True
            endpoint='/api/v1/setup/confirmation' if action=='confirm' else '/api/v1/setup'
            assert shared.http.request('POST',endpoint,shared.headers,payload)[0]==200
            shared.wait(lambda:shared.client.execute({'action':'setup-status','run_id':shared.run_id,'request_id':request_id})['status']!='pending')
        shared.wait(lambda:shared.status(shared.run_id)['status']=='completed')
        assert len(shared.backend.calls)==2
