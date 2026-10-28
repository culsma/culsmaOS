"""Files launch opens a dedicated result window; reopening never reruns a protocol."""
import json
import os
import subprocess
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME']),reason='Explicit local browser environment required')
def test_double_click_executes_once_and_result_survives_window_close(tmp_path):
    with SharedSetupHarness(tmp_path,submit=False,programs=True) as shared:
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/window_launch_browser.mjs'),shared.url],
            capture_output=True,text=True,timeout=65,cwd=ROOT)
        assert result.returncode==0,result.stderr
        outcome=json.loads(result.stdout)
        assert outcome['start_requests']==1
        assert shared.status(outcome['run_id'])['status']=='completed'
        assert len(shared.client.execute({'action':'runs'})['runs'])==1
        assert len(shared.backend.calls)==2
