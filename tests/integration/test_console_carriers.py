"""Real HTTP/configuration activation and browser checks for native rack replacement."""
import json
import os
import subprocess
import pytest
from tests.support.paths import ROOT
from tests.support.integration.console_labware import native_station, request


def test_carrier_proposal_requires_explicit_activation_and_preserves_execution(tmp_path,monkeypatch):
    with native_station(tmp_path,monkeypatch) as shared:
        original=shared.context.config_path.read_bytes()
        fp=shared.client.execute({'action':'configuration-status'})['active']['fingerprint']
        change={'action':'replace-carrier','target':'carrier:PREVIEW_T37_38_4R200','model':'RGT_CAR_5R60_A00'}
        assert request(shared,'prepare','0'*64,change=change)[0]==409
        code,_,body=request(shared,'prepare',fp,change=change)
        assert code==200,body
        proposal=body['data'];draft=proposal['draft']
        assert proposal['activation']=='not_applied'
        assert shared.client.execute({'action':'configuration-status'})['active']['fingerprint']==fp
        assert shared.context.config_path.read_bytes()==original
        assert not shared.client.execute({'action':'runs'})['runs'] and not shared.backend.calls
        code,_,reply=shared.http.request('POST','/api/v1/configuration/activation',shared.headers,
            {'action':'apply','draft_id':draft['draft_id'],'revision':draft['revision'],'expected_fingerprint':fp,'request_id':'rack-change'})
        assert code==200,reply
        shared.wait(lambda:shared.client.execute({'action':'configuration-status'})['receipt']['status']=='applied')
        layout=shared.client.execute({'action':'layout-status'})['layout']['definition']
        carrier=next(row for row in layout['objects'] if row['id']=='PREVIEW_T37_38_4R200')
        assert carrier['model']=='RGT_CAR_5R60_A00' and carrier['site']=='1T-37'
        assert shared.context.config_path.read_bytes()==original
        assert not shared.backend.calls


@pytest.mark.skipif(not os.environ.get('CULSMA_OS_BROWSER_MODULES'),reason='Local browser required')
def test_native_carrier_settings_browser(tmp_path,monkeypatch):
    with native_station(tmp_path,monkeypatch) as shared:
        output=ROOT/'run-artifacts/ui-tests';output.mkdir(parents=True,exist_ok=True)
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/carriers_browser.mjs'),
            shared.url,str(output),str(ROOT/'tests/modules/console/goldens')],capture_output=True,text=True,timeout=90,cwd=ROOT)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['applied']
        assert not shared.client.execute({'action':'runs'})['runs'] and not shared.backend.calls
