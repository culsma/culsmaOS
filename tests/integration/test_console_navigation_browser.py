"""The revised navigation operates on one resident without creating device work."""
import json
import os
import subprocess
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME']),reason='Explicit local browser environment required')
def test_single_workstation_navigation_preserves_the_loading_gate(tmp_path,monkeypatch):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    from pathlib import Path
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    output=ROOT/'run-artifacts/ui-tests';output.mkdir(parents=True,exist_ok=True)
    with SharedSetupHarness(tmp_path) as shared:
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/navigation_browser.mjs'),
            shared.url,shared.run_id,str(output),str(ROOT/'tests/modules/console/goldens')],capture_output=True,text=True,timeout=60,cwd=ROOT)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['navigation_writes']==0
        assert shared.status(shared.run_id)['status']=='awaiting_setup'
        assert not shared.backend.calls
