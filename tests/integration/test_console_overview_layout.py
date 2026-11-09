"""Configured Hamilton geometry is visible before any program, import or device action."""
import json
import os
from pathlib import Path
import subprocess
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME']),reason='Explicit local browser environment required')
def test_overview_reads_full_startup_layout_without_submission_or_import(tmp_path,monkeypatch):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    from culsma_driver_hamilton.assembly import build_configuration_profile
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    source=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
    report=build_configuration_profile().import_layout(source.read_bytes(),source.name)
    shared=SharedSetupHarness(tmp_path,submit=False)
    configuration=json.loads(shared.context.config_path.read_text())
    configuration['layout']=report['configuration']
    configuration['execution']['tips']={'labware':'HTF_B4_TEST','available_positions':['1','2','3','4','5','6']}
    configuration['execution']['capacities_uL']={'WATER_T36_REAR_SITE1':60000,'DWP96_E4':2200}
    configuration['bindings']={};configuration['well_positions']={}
    shared.context.config_path.write_text(json.dumps(configuration))
    before=shared.context.config_path.read_bytes()
    output=ROOT/'run-artifacts/ui-tests';output.mkdir(parents=True,exist_ok=True)
    with shared:
        code,_,station=shared.http.request('GET','/api/v1/station')
        assert code==200 and not station['data']['runs']
        layout=station['data']['layout']
        assert layout['status']=='available' and layout['source']=='active_host_configuration'
        assert len(layout['layout']['definition']['objects'])==91
        assert layout['layout']['configuration']=={}
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/overview_layout_browser.mjs'),
            shared.url,str(output),str(ROOT/'tests/modules/console/goldens')],capture_output=True,text=True,timeout=60,cwd=ROOT)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['posts']==0
        assert not shared.client.execute({'action':'runs'})['runs'] and not shared.backend.calls
    assert shared.context.config_path.read_bytes()==before


def test_opentrons_startup_layout_is_available_without_running_a_program(tmp_path):
    pytest.importorskip('opentrons')
    from tests.support.console.http import ConsoleProtocolHarness, ConsoleHTTPHarness
    from culsma_os.console.models import ConsoleSettings
    from culsma_os.console.providers import ConsoleApplicationFactory
    with ConsoleProtocolHarness(tmp_path,'transfer') as resident:
        server=ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint,0))
        with ConsoleHTTPHarness(server) as console:
            code,_,snapshot=console.request('GET','/api/v1/station')
            assert code==200 and not snapshot['data']['runs']
            descriptor=snapshot['data']['layout']
            assert descriptor['status']=='available' and descriptor['hardware_observed'] is False
            assert descriptor['layout']['configuration']['robot_type']=='OT-2'
            assert 'bindings' not in descriptor['layout']['configuration']
            assert len(descriptor['layout']['definition']['variants']['OT-2']['positions'])==12
