"""MCP settings use the real Auth owner, SQLite store and installed driver profiles."""
from copy import deepcopy
from pathlib import Path
import base64
import json
import pytest
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.workspace_manager.models import ConfigurationError, StationConfigurationRequest


@pytest.fixture
def settings(tmp_path,monkeypatch):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    value=ConsoleSettings(tmp_path/'station.sock',0,tmp_path/'drafts.sqlite3',tmp_path/'projects',tmp_path/'snapshots',tmp_path/'Home',serve_frontend=False)
    factory=ConsoleApplicationFactory()
    from culsma_os.device_manager.interactors import DeviceProfileInteractor
    from culsma_os.driver_framework.interactors import DriverProfileInteractor
    bridge=factory.build_mcp(value,profiles=DeviceProfileInteractor(DriverProfileInteractor()))
    bridge.server.raw_credential='Bearer '+bridge.tokens.issue_automation_session()
    return bridge, factory, value, driver


def test_mcp_and_http_share_revisions_and_preserve_stale_edits(settings):
    bridge,factory,value,_=settings;tools=bridge.server
    http=factory.build(value)
    try:
        human='Bearer '+http.sessions.tokens.issue_console_session()
        profiles=tools.configuration_profiles()
        profile=next(p for p in profiles['profiles'] if p['driver']=='hamilton-layout')
        draft=tools.create_configuration('AI setup',profile['driver'],profile['template'])['draft']
        assert http.configuration.execute(human,StationConfigurationRequest('get',draft['draft_id']))['draft']==draft
        copied=deepcopy(draft['configuration'])
        saved=tools.save_configuration(draft['draft_id'],draft['revision'],'Edited by AI',draft['driver'],copied)['draft']
        assert saved['revision']==2
        with pytest.raises(ConfigurationError,match='CONFIGURATION_REVISION_CONFLICT'):
            tools.save_configuration(draft['draft_id'],1,'Stale human edit',draft['driver'],copied)
        assert tools.read_configuration(draft['draft_id'])['draft']==saved
        assert tools.read_configuration(draft['draft_id'],1)['draft']==draft
        assert any(row['draft_id']==draft['draft_id'] for row in tools.list_configurations()['drafts'])
        validation=tools.validate_configuration(saved['draft_id'],2)
        assert isinstance(validation['validation']['valid'],bool)
    finally:http.server_close()


def test_vendor_conversion_validation_and_archives_use_real_driver(settings):
    bridge,_,_,driver=settings;tools=bridge.server
    path=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
    imported=tools.import_vendor_layout('hamilton-layout',{'name':path.name,'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode()})
    assert imported['import_report']['complete']
    draft=tools.create_configuration('Imported layout','hamilton-layout',imported['import_report']['configuration'])['draft']
    assert tools.validate_configuration(draft['draft_id'],1)['validation']['valid']
    assert tools.export_configuration(draft['draft_id'],1)['configuration']==draft['configuration']
    exported=tools.export_vendor_layout(draft['draft_id'],1)
    assert exported['layout_artifact']['encoding']=='base64'
    assert base64.b64decode(exported['layout_artifact']['content']).startswith(b'PK')
    with pytest.raises(ConfigurationError):tools.import_vendor_layout('hamilton-layout',{'name':'bad.lay','encoding':'base64','content':'invalid!'})
    with pytest.raises(ConfigurationError,match='CONFIGURATION_OFFLINE_ONLY'):
        tools.apply_configuration(draft['draft_id'],1,'a'*64,'offline-cannot-activate')


@pytest.mark.parametrize('method,arguments',[
    ('configuration_profiles',{}),('list_configurations',{}),
    ('create_configuration',{'title':'Denied','driver':'hamilton-layout','configuration':{}}),
    ('configuration_status',{}),
    ('labware_catalogue',{'expected_fingerprint':'a'*64}),
    ('test_device_fault',{'scenario':'tip_unavailable'}),
])
def test_renderer_cannot_use_any_business_settings_tools(settings,method,arguments):
    bridge,_,value,_=settings
    bridge.server.raw_credential='Bearer '+bridge.tokens.issue_renderer_session()
    with pytest.raises(ConsoleAccessError):getattr(bridge.server,method)(**arguments)
    assert not value.drafts_path.exists()


def test_invalid_configuration_and_unknown_host_do_not_apply(settings):
    bridge,_,value,_=settings;tools=bridge.server
    with pytest.raises(ConfigurationError):tools.create_configuration('NaN','hamilton-layout',{'value':float('nan')})
    with pytest.raises(ConfigurationError):tools.save_configuration('missing',True,'Bad','hamilton-layout',{})
    with pytest.raises(ConfigurationError,match='CONFIGURATION_HOST_RESPONSE_UNAVAILABLE'):tools.configuration_status()
    assert not value.socket_path.exists()
