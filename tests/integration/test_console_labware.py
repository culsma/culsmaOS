"""Actual protected HTTP -> resident -> driver -> saved activation path."""
import json
import os
from pathlib import Path
import subprocess
import pytest
from tests.support.integration.shared_setup import SharedSetupHarness
from tests.support.paths import ROOT


def request(shared, action, fingerprint, **extra):
    return shared.http.request('POST','/api/v1/configuration/labware',shared.headers,
                               {'action':action,'expected_fingerprint':fingerprint,**extra})


def native_station(tmp_path, monkeypatch):
    import culsma_driver_hamilton
    from culsma_driver_hamilton.assembly import build_configuration_profile
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    source=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
    shared=SharedSetupHarness(tmp_path,submit=False)
    configuration=json.loads(shared.context.config_path.read_text())
    configuration['layout']=build_configuration_profile().import_layout(source.read_bytes(),source.name)['configuration']
    configuration['execution']['tips']={'labware':'HTF_B4_TEST','available_positions':['1','2','3','4','5','6']}
    configuration['execution']['capacities_uL']={'WATER_T36_REAR_SITE1':60000,'DWP96_E4':2200}
    configuration['bindings']={};configuration['well_positions']={}
    shared.context.config_path.write_text(json.dumps(configuration))
    return shared


def test_labware_checks_auth_staleness_and_busy_station(tmp_path):
    with SharedSetupHarness(tmp_path,submit=False) as shared:
        fp=shared.client.execute({'action':'configuration-status'})['active']['fingerprint']
        status,_,body=shared.http.request('POST','/api/v1/configuration/labware',{'Origin':shared.url,'Content-Type':'application/json'},
            {'action':'catalogue','expected_fingerprint':fp})
        assert status==401
        assert request(shared,'catalogue','0'*64)[0]==409
        status,_,body=request(shared,'catalogue',fp)
        assert status==200,body
        target=next(t for t in body['data']['catalogue']['targets'] if t['models'] and not t['occupants'])
        assert request(shared,'prepare',fp,change={'action':'place','target':target['id'],'name':'Extra','model':'invented'})[0]==409
        shared.client.execute({'action':'submit','source':str(shared.source)})
        assert request(shared,'catalogue',fp)[0]==409
        assert not shared.backend.calls


def test_native_proposal_is_detached_and_activation_is_explicit(tmp_path,monkeypatch):
    with native_station(tmp_path,monkeypatch) as shared:
        original=shared.context.config_path.read_bytes()
        fp=shared.client.execute({'action':'configuration-status'})['active']['fingerprint']
        status,_,body=request(shared,'prepare',fp,change={'action':'place','target':'PREVIEW_T36_5R60_SUBSTITUTE/2',
            'name':'ExtraVessel','model':'RGT_CONT_60ML_BC_A00'})
        assert status==200,body
        proposal=body['data'];assert 'configuration' not in proposal
        assert proposal['activation']=='not_applied' and proposal['physical_observation'] is False
        assert len(proposal['layout']['definition']['objects'])==92
        assert shared.context.config_path.read_bytes()==original
        assert shared.client.execute({'action':'configuration-status'})['active']['fingerprint']==fp
        draft=proposal['draft']
        status,_,reply=shared.http.request('POST','/api/v1/configuration/activation',shared.headers,
            {'action':'apply','draft_id':draft['draft_id'],'revision':draft['revision'],
             'expected_fingerprint':fp,'request_id':'apply-extra-vessel'})
        assert status==200,reply
        shared.wait(lambda:shared.client.execute({'action':'configuration-status'})['receipt']['status']=='applied')
        assert shared.client.execute({'action':'configuration-status'})['active']['fingerprint']!=fp
        layout=shared.client.execute({'action':'layout-status'})['layout']['definition']
        assert len(layout['objects'])==92 and any(o['id']=='ExtraVessel' for o in layout['objects'])
        assert request(shared,'catalogue',fp)[0]==409
        new_fp=shared.client.execute({'action':'configuration-status'})['active']['fingerprint']
        status,_,catalogue=request(shared,'catalogue',new_fp)
        assert status==200,catalogue
        assert not shared.backend.calls and not shared.client.execute({'action':'runs'})['runs']
        assert shared.context.config_path.read_bytes()==original


@pytest.mark.skipif(not os.environ.get('CULSMA_OS_BROWSER_MODULES'),reason='Local browser required')
def test_native_labware_browser(tmp_path,monkeypatch):
    with native_station(tmp_path,monkeypatch) as shared:
        output=ROOT/'run-artifacts/ui-tests';output.mkdir(parents=True,exist_ok=True)
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/labware_browser.mjs'),
            shared.url,str(output/'labware-editor.png'),str(ROOT/'tests/modules/console/goldens')],capture_output=True,text=True,timeout=90,cwd=ROOT)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['applied'] is True
        assert not shared.backend.calls and not shared.client.execute({'action':'runs'})['runs']
