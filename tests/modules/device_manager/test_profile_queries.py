"""Actual installed offline profiles and the production bounded local socket transport."""
import base64
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4
import pytest
from culsma_os.device_manager.interactors import DeviceProfileInteractor,ResidentDeviceProfileInteractor,RemoteDeviceProfileInteractor
from culsma_os.device_manager.models import DeviceProfileQueryError
from culsma_os.driver_framework.interactors import DriverProfileInteractor
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter,ResidentSocketAdapter,ResidentProtocolAdapter
from culsma_os.program_manager.interactors.resident import ResidentCommandInteractor


@pytest.fixture
def profiles(monkeypatch):
    import culsma_driver_hamilton
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    return ResidentDeviceProfileInteractor(DeviceProfileInteractor(DriverProfileInteractor())),driver


@pytest.fixture
def remote(profiles):
    owner,driver=profiles
    commands=ResidentCommandInteractor(None,None,None,None,None,None,None,None,None,profile_queries=owner)
    path=Path('/private/tmp')/('culsma-profile-'+uuid4().hex[:12]+'.sock')
    server=ResidentSocketAdapter(path,commands);server.open();stop=Event()
    def serve():
        while not stop.is_set():server.handle_one()
    thread=Thread(target=serve);thread.start()
    try:yield RemoteDeviceProfileInteractor(ResidentClientAdapter(path,2)),driver
    finally:stop.set();thread.join(3);server.close();assert not thread.is_alive()


def test_profile_operations_cross_the_actual_resident_transport(remote):
    query,driver=remote
    profile=next(p for p in query.describe()['profiles'] if p['driver']=='hamilton-layout')
    assert isinstance(query.validate('hamilton-layout',profile['template'])['valid'],bool)
    path=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
    imported=query.import_layout('hamilton-layout',{'name':path.name,'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode()})
    assert imported['complete']
    assert query.validate('hamilton-layout',imported['configuration'])['valid']
    exported=query.export_layout('hamilton-layout',imported['configuration'])
    assert base64.b64decode(exported['content']).startswith(b'PK')
    assert query.program_bindings('hamilton-layout',imported['configuration']) is None
    assert query.import_layout('missing-profile',{'name':'test.lay','encoding':'base64','content':'YQ=='}) is None
    assert not query.validate('missing-profile',{})['valid']
    with pytest.raises(DeviceProfileQueryError,match='PROFILE_LAYOUT_IMPORT_INVALID'):
        query.import_layout('hamilton-layout',{'name':'bad.lay','encoding':'base64','content':'!invalid!'})


@pytest.mark.parametrize('profile_request',[None,{}, {'action':[]},{'action':'__getattribute__'},
    {'action':'describe','driver':'unexpected'},{'action':'validate','driver':'../driver','configuration':{}},
    {'action':'validate','driver':'hamilton-layout','configuration':None},
    {'action':'validate','driver':'hamilton-layout','configuration':{'x':float('nan')}},
    {'action':'import_layout','driver':'hamilton-layout','configuration':{},'layout_source':{}},
    {'action':'describe','extra':True}])
def test_invalid_profile_queries_are_rejected_by_the_owner(profiles,profile_request):
    with pytest.raises(ValueError,match='DEVICE_PROFILE_REQUEST_INVALID'):profiles[0].execute(profile_request)


def test_profile_query_limits_and_response_shapes_are_explicit(profiles):
    owner,_=profiles
    with pytest.raises(ValueError,match='DEVICE_PROFILE_REQUEST_INVALID'):
        owner.execute({'action':'validate','driver':'hamilton-layout','configuration':{'x':'x'*(2*1024*1024)}})
    for value in [[],True,None,{'value':float('nan')},{'value':object()},{'value':'x'*(4*1024*1024)}]:
        with pytest.raises(ValueError,match='DEVICE_PROFILE_RESPONSE_INVALID'):owner.validate_response('describe',value)
    assert owner.validate_response('program_bindings',None) is None


def test_missing_resident_profile_service_never_loads_local_driver_or_falls_back(tmp_path):
    query=RemoteDeviceProfileInteractor(ResidentClientAdapter(tmp_path/'missing.sock',1))
    with pytest.raises(DeviceProfileQueryError,match='CONFIGURATION_PROFILE_HOST_UNAVAILABLE'):query.describe()
    assert not list(tmp_path.iterdir())


def test_profile_transport_preserves_data_and_rejects_non_object_payload():
    value={'action':'configuration-profile','profile_request':{'action':'describe'}}
    assert ResidentProtocolAdapter.request(value).profile_request==value['profile_request']
    with pytest.raises(ValueError,match='HOST_REQUEST_INVALID'):
        ResidentProtocolAdapter.request({'action':'configuration-profile','profile_request':[]})
