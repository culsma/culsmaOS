"""Graph and human confirmation follow the same MCP-revised frozen loading plan."""
import json
import os
import subprocess
import sys
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_MCP_SDK_PATH','CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME']),
    reason='Explicit browser and MCP SDK test environments required')
def test_graphical_loading_plan_tracks_mcp_revision_and_invalidates_operator_acknowledgement(tmp_path,monkeypatch):
    import culsma_driver_hamilton
    from pathlib import Path
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    shared=SharedSetupHarness(tmp_path)
    config=json.loads(shared.context.config_path.read_text())
    config['layout']['labware']['source_other']={**config['layout']['labware']['source_vessel'],'site':'2'}
    config['execution']['capacities_uL']['source_other']=60000
    config['execution']['tips']['available_positions']=[str(n) for n in range(1,13)]
    config['well_positions']={'destination_plate':{f'{chr(65+r)}{c}':str((c-1)*8+r+1) for c in range(1,13) for r in range(8)}}
    shared.context.config_path.write_text(json.dumps(config))
    shared.source.write_text('''let source=tube(capacity=60mL,load=[content(kind=formulation,type=buffer,code="STANDARD"):1mL]);
let diluent=tube(capacity=60mL,load=[content(kind=formulation,type=buffer,code="DILUENT"):1mL]);
let p=plate(format="96well",capacity=2000uL);let wells=p[A1:A3];
wells[0] << [source:10uL,diluent:90uL];wells[1] << [source:20uL,diluent:80uL];wells[2] << [source:40uL,diluent:60uL];return wells;''')
    artifacts=ROOT/'run-artifacts/ui-tests';artifacts.mkdir(parents=True,exist_ok=True)
    with shared:
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/loading_layout_browser.mjs'),
            shared.url,shared.run_id,str(shared.endpoint),str(artifacts),str(ROOT/'tests/modules/console/goldens')],
            env={**os.environ,'CULSMA_OS_TEST_PYTHON':sys.executable},capture_output=True,text=True,timeout=60,cwd=ROOT)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['required_wells']==['A1','A2','A3']
        shared.wait(lambda:shared.status(shared.run_id)['status']=='completed')
        assert len(shared.backend.calls)==3
        prepared=shared.backend.calls[0][0]
        source=prepared.intent.aliquots[0].source.container_id
        assert next(row for row in prepared.report['bindings'] if row['container_id']==source)['labware']=='source_other'
