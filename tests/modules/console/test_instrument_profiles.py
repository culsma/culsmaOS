"""Real HTTP and MCP methods share Auth, actual driver rules and durable storage."""
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.adapters.mcp import MCPServerAdapter
from culsma_os.console.adapters.instrument_profiles import InstrumentProfileRequestMapper
from culsma_os.console.models import ConsoleSettings
from culsma_os.device_manager.instruments.models import ModuleProfileError
from culsma_os.device_manager.instruments.profile_api_models import InstrumentProfileRequest
from tests.support.device_manager.profile_api import ProfileAPIFixture


@pytest.fixture
def api(tmp_path):
    fixture = ProfileAPIFixture(tmp_path)
    server = ConsoleHTTPServer(ConsoleSettings(tmp_path/'absent.sock', 0), None, instrument_profiles=fixture.owner)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}); thread.start()
    tools = MCPServerAdapter(None, None, None, instrument_profiles=fixture.owner)
    tools.raw_credential = fixture.credential
    def post(payload, raw=fixture.credential):
        request = Request(server.url+'/api/v1/instrument-profiles', json.dumps(payload).encode(),
            {'Origin': server.url, 'Content-Type': 'application/json', 'Authorization': raw}, method='POST')
        try:
            with urlopen(request, timeout=5) as response: return response.status, json.load(response)
        except HTTPError as error: return error.code, json.load(error)
    try: yield fixture, tools, post
    finally: server.shutdown(); thread.join(5); server.server_close()


def test_mcp_to_http_and_http_to_mcp_roundtrip(api):
    fixture, tools, post = api
    catalogue = tools.instrument_profile_catalogue(**fixture.context)
    assert {m['kind'] for m in catalogue['modules']} == {'magnet', 'pipetting'}
    assert tools.validate_instrument_profile(**fixture.values)['valid']
    saved = tools.save_instrument_profile(**fixture.values)['profile']
    reference = saved['reference']
    read = dict(device_id=reference['device_id'], module_id=reference['module_id'],
        profile_id=reference['profile_id'], profile_revision=reference['revision'])
    status, result = post({'action': 'read', **read})
    assert status == 200 and result['data']['profile'] == saved
    status, result = post({'action': 'save', **fixture.values, 'expected_revision': reference['revision'],
        'parameters': {**fixture.values['parameters'], 'aspiration_height_mm': 6.0}})
    assert status == 200
    revision = result['data']['profile']['reference']['revision']
    assert tools.read_instrument_profile(**{**read, 'profile_revision': revision})['profile']['parameters']['aspiration_height_mm'] == 6
    assert len(tools.list_instrument_profiles(reference['device_id'], reference['module_id'])['profiles']) == 2
    assert post({'action': 'save', **fixture.values})[0] == 409
    assert post({'action': 'read', **read, 'profile_revision': 'missing'})[0] == 404
    assert fixture.repository.get(fixture.draft['draft_id']).as_dict() == fixture.draft


def test_http_authorization_and_transport_fields(api):
    fixture, tools, post = api
    request = {'action': 'save', **fixture.values}
    assert post(request, 'Bearer invalid')[0] == 401
    assert post(request, 'Bearer '+fixture.tokens.issue_renderer_session())[0] == 403
    for extra in ({'caller': 'admin'}, {'path': '/tmp/ignored'}, {'module': {'driver_id': 'fake'}}, {'configuration_revision': True}):
        assert post({**request, **extra})[0] == 400
    assert not fixture.profiles.path.exists()


def test_static_magnet_profile_is_independent_and_does_not_start_a_run(api):
    fixture, tools, post = api
    data = {**fixture.context, 'module_id': 'magnet', 'profile_id': 'passive-rack',
        'method_id': 'passive_magnet', 'definition_revision': '1', 'display_name': 'Configured rack',
        'parameters': {'labware': ['destination_plate']}}
    status, result = post({'action': 'save', **data})
    assert status == 200 and result['data']['activation'] == 'not_applied'
    assert result['data']['run_binding'] == 'not_bound'
    assert tools.list_instrument_profiles(data['device_id'], data['module_id'])['profiles']
    assert tools.list_instrument_profiles(data['device_id'], fixture.values['module_id'])['profiles'] == []


@pytest.mark.parametrize('payload',[{}, [], {'action': 'list', 'device_id': 42},
    {'action': 'save', 'device_id': 'd', 'parameters': []}, {'action': 'list', 'device_id': 'd', 'scopes': []}])
def test_mapper_rejects_bad_transport_shape(payload):
    with pytest.raises(ModuleProfileError): InstrumentProfileRequestMapper().parse(payload)


def test_portable_profile_applicability_survives_mcp_http_and_revision_update(api):
    fixture, tools, post = api
    scope = {'operation': 'magnetic_flowthrough_transfer',
        'source_models': ['Ham_DW_Rgt_96_L'], 'destination_models': ['RGT_CONT_60ML_BC_A00'],
        'tip_models': ['HTF_L'], 'per_aspiration_volume_uL': {'minimum': 10, 'maximum': 300},
        'required_source_conditions': ['magnetically_held']}
    values = {**fixture.values, 'method_id': 'positioned_pipetting',
        'parameters': {'aspiration_height_mm': 4, 'dispense_height_mm': 5}, 'applicability': scope}
    first = tools.save_instrument_profile(**values)['profile']
    assert first['applicability'] == scope
    assert 'liquid_class' not in first['parameters']
    status, result = post({'action': 'save', **values, 'expected_revision': first['reference']['revision'],
        'parameters': {**values['parameters'], 'aspiration_height_mm': 3.5}})
    assert status == 200 and result['data']['profile']['applicability'] == scope
    reference = first['reference']
    old = tools.read_instrument_profile(reference['device_id'], reference['module_id'], reference['profile_id'], reference['revision'])['profile']
    assert old['parameters']['aspiration_height_mm'] == 4
    assert old['applicability'] == scope
    assert post({'action': 'save', **values, 'applicability': {**scope, 'native_code': 'unknown'}})[0] == 400
    invalid = {**scope, 'tip_models': ['other']}
    assert tools.validate_instrument_profile(**{**values, 'applicability': invalid})['valid'] is False
    assert len(tools.list_instrument_profiles(reference['device_id'], reference['module_id'])['profiles']) == 2
