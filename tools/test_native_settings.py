"""Official MCP -> real local OS/driver configuration -> native settings; no device actions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness
from tests.support.integration.console_labware import native_station


class TestEnvironment:
    def setenv(self,key,value):os.environ[key]=value


def run():
    output=ROOT/'run-artifacts/native-settings';output.mkdir(parents=True,exist_ok=True)
    sdk=os.environ['CULSMA_OS_MCP_SDK_PATH']
    flutter=os.environ['CULSMA_OS_FLUTTER']
    with tempfile.TemporaryDirectory(prefix='culsma-native-settings-') as temporary:
        base=Path(temporary)
        with native_station(base,TestEnvironment()) as shared:
            home=base/'Home';programs=home/'projects';programs.mkdir(parents=True)
            settings=ConsoleSettings(shared.endpoint,0,base/'drafts.sqlite3',programs,base/'snapshots',home,serve_frontend=False)
            server=ConsoleApplicationFactory().build(settings)
            raw=server.sessions.tokens.issue_console_session()
            with ConsoleHTTPHarness(server) as http:
                headers={'Origin':server.url,'Authorization':'Bearer '+raw,'Content-Type':'application/json'}
                code,_,saved=http.request('POST','/api/v1/configuration/drafts',headers,{'action':'create','title':'Human baseline','driver':'hamilton-agent','configuration':json.loads(shared.context.config_path.read_text())})
                assert code==200,saved
                env={**os.environ,'CULSMA_SETTINGS_TEST_ORIGIN':server.url,'CULSMA_SETTINGS_TEST_TOKEN':raw,'CULSMA_SETTINGS_BASE_DRAFT':saved['data']['draft']['draft_id'],'CULSMA_SETTINGS_RENDERER_TOKEN':server.sessions.tokens.issue_renderer_session()}
                with (output/'flutter-e2e.log').open('w') as log:
                    native=subprocess.Popen([flutter,'test','integration_test/settings_mcp_test.dart','-d','macos','--no-pub'],cwd=ROOT/'frontend/console',env=env,stdout=log,stderr=subprocess.STDOUT)
                    try:
                        deadline=time.monotonic()+120
                        ready=False
                        while time.monotonic()<deadline:
                            assert native.poll() is None,'Native settings test exited; see flutter-e2e.log'
                            code,_,reply=http.request('POST','/api/v1/console/views/read',headers,{'action':'sessions'})
                            if code==200 and any(session['online'] and session['state']['dirty'] for session in reply['data']['sessions']):
                                ready=True;break
                            time.sleep(.1)
                        assert ready,'Native settings did not become ready'
                        import culsma_driver_hamilton
                        driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
                        source=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
                        result=subprocess.run([sys.executable,'-m','tests.support.console.settings_mcp_client',str(shared.endpoint),str(home),str(programs),str(settings.program_store),str(settings.drafts_path),str(source)],cwd=ROOT,env={**os.environ,'PYTHONPATH':sdk+os.pathsep+str(ROOT/'src')+os.pathsep+str(driver/'src')},capture_output=True,text=True,timeout=60)
                        (output/'mcp-e2e.log').write_text(result.stderr+'\n'+result.stdout)
                        assert result.returncode==0,'MCP settings failed; see mcp-e2e.log'
                        assert native.wait(timeout=35)==0,'Native settings failed; see flutter-e2e.log'
                        text=(output/'flutter-e2e.log').read_text()
                        assert 'Failed to update ui::AXTree' not in text and 'Lost connection to device' not in text
                        assert not shared.backend.calls and not shared.client.execute({'action':'runs'})['runs']
                        print('Native settings passed: actual MCP rack/slot changes visible, shared revisions, unsaved human layout retained, stale apply blocked, explicit discard follows current configuration. No device actions.')
                    finally:
                        if native.poll() is None:native.terminate();native.wait(timeout=10)


if __name__=='__main__':run()
