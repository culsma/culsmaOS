import base64
from copy import deepcopy
from hashlib import sha256
import pytest
from culsma_os.device_manager.interactors import DeviceProfileInteractor
from culsma_os.driver_framework.models import LayoutImportError


from tests.support.device_manager.layout_import import source,report,ExternalProfile,Discovery


def test_optional_import_delegates_bytes_without_interpreting_vendor_format():
    profile=ExternalProfile();interactor=DeviceProfileInteractor(Discovery(profile))
    assert interactor.import_layout('missing',source()) is None
    assert interactor.import_layout('external',source())==report()
    assert profile.calls==[(b'native bytes','layout.bin')]
    profile.result=report(complete=False)
    assert interactor.import_layout('external',source())['configuration'] is None


@pytest.mark.parametrize('change',[{'encoding':'text'},{'content':'!'},{'name':'../file'}, {'content':'A'*1400001}])
def test_invalid_sources_never_reach_plugin(change):
    profile=ExternalProfile();interactor=DeviceProfileInteractor(Discovery(profile))
    with pytest.raises(LayoutImportError):interactor.import_layout('external',{**source(),**change})
    assert not profile.calls


@pytest.mark.parametrize('fault',['source','schema','complete','accepted-incomplete','activation','physical','geometry','duplicate','nan'])
def test_untrusted_driver_report_cannot_forge_a_valid_conversion(fault):
    value=report()
    if fault=='source':value['source']['sha256']='wrong'
    if fault=='schema':value['schema']='vendor-private'
    if fault=='complete':value['complete']='yes'
    if fault=='accepted-incomplete':value['complete']=False
    if fault=='activation':value['activation']='applied'
    if fault=='physical':value['physical_observation']=True
    if fault=='geometry':value['objects'][0]['origin_mm']=[]
    if fault=='duplicate':value['objects']*=2
    if fault=='nan':value['objects'][0]['angle_deg']=float('nan')
    with pytest.raises(LayoutImportError):DeviceProfileInteractor(Discovery(ExternalProfile(value))).import_layout('external',source())
