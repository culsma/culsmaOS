"""An occupied native site stays editable; configuration activation is still explicit."""
from tests.integration.test_console_labware import native_station,request


def apply(shared,proposal,fp,identity):
    draft=proposal['draft']
    code,_,body=shared.http.request('POST','/api/v1/configuration/activation',shared.headers,
        {'action':'apply','draft_id':draft['draft_id'],'revision':draft['revision'],
         'expected_fingerprint':fp,'request_id':identity})
    assert code==200,body
    shared.wait(lambda:shared.client.execute({'action':'configuration-status'})['receipt']['status']=='applied')


def test_existing_tip_model_changes_without_rack_change(tmp_path,monkeypatch):
    with native_station(tmp_path,monkeypatch) as shared:
        fp=shared.client.execute({'action':'configuration-status'})['active']['fingerprint']
        before=shared.client.execute({'action':'layout-status'})['layout']['definition']['objects']
        code,_,body=request(shared,'prepare',fp,change={'action':'replace','target':'CAR_5TIP_0001/2','model':'ST_L.rck'})
        assert code==200,body
        proposal=body['data'];assert proposal['activation']=='not_applied'
        assert shared.client.execute({'action':'configuration-status'})['active']['fingerprint']==fp
        apply(shared,proposal,fp,'replace-existing-htl')
        after=shared.client.execute({'action':'layout-status'})['layout']['definition']['objects']
        assert next(row for row in after if row['id']=='HT_L_0003')['model']=='ST_L.rck'
        assert [row for row in before if row['category']=='carrier']==[row for row in after if row['category']=='carrier']
        assert not shared.backend.calls and not shared.client.execute({'action':'runs'})['runs']


def test_removing_active_tip_source_keeps_station_configurable_without_false_supply(tmp_path,monkeypatch):
    with native_station(tmp_path,monkeypatch) as shared:
        fp=shared.client.execute({'action':'configuration-status'})['active']['fingerprint']
        code,_,body=request(shared,'prepare',fp,change={'action':'remove','target':'CAR_5TIP_0002/4'})
        assert code==200,body
        assert any('tip source' in message for message in body['data']['impact'])
        apply(shared,body['data'],fp,'remove-current-tip-source')
        assert shared.client.execute({'action':'host-status'})['status']=='ready'
        after=shared.client.execute({'action':'layout-status'})['layout']['definition']['objects']
        assert not any(row['id']=='HTF_B4_TEST' for row in after)
        assert not shared.backend.calls and not shared.client.execute({'action':'runs'})['runs']
