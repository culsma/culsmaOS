"""Real SDK -> MCP -> shared configuration database -> resident -> installed driver."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.support.integration.console_labware import native_station
from tests.support.paths import ROOT


@pytest.mark.skipif(not os.environ.get('CULSMA_OS_MCP_SDK_PATH'),reason='Explicit isolated official MCP SDK required')
def test_mcp_settings_change_the_same_station_and_drafts_as_http(tmp_path,monkeypatch):
    import culsma_driver_hamilton
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    source=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
    with native_station(tmp_path,monkeypatch) as shared:
        original=shared.context.config_path.read_bytes()
        home=tmp_path/'Home';programs=home/'projects';programs.mkdir(parents=True)
        env={**os.environ,'PYTHONPATH':os.environ['CULSMA_OS_MCP_SDK_PATH']+os.pathsep+str(ROOT/'src')+os.pathsep+str(driver/'src')}
        result=subprocess.run([sys.executable,'-m','tests.support.console.settings_mcp_client',str(shared.endpoint),str(home),str(programs),str(tmp_path/'snapshots'),str(tmp_path/'drafts.sqlite3'),str(source)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        result=json.loads(result.stdout)
        assert result['tools']>=43
        code,_,reply=shared.http.request('POST','/api/v1/configuration/drafts',shared.headers,{'action':'get','draft_id':result['draft_id']})
        assert code==200 and reply['data']['draft']['title']=='Rack edited through MCP'
        layout=shared.client.execute({'action':'layout-status'})['layout']['definition']
        rack=next(o for o in layout['objects'] if o['id']=='PREVIEW_T37_38_4R200')
        assert rack['model']=='RGT_CAR_5R60_A00'
        assert not any(o['id']=='MCPVessel' for o in layout['objects'])
        assert shared.client.execute({'action':'configuration-status'})['active']['fingerprint']==result['active_fingerprint']
        assert not shared.backend.calls and not shared.client.execute({'action':'runs'})['runs']
        assert shared.context.config_path.read_bytes()==original
