import base64
from hashlib import sha256
import json
import pytest
from culsma_os.device_manager.interactors import DeviceProfileInteractor
from culsma_os.driver_framework.models import LayoutExportError


def artifact(configuration):
    content=b'PK\x03\x04fixture'
    return {'name':'layout.zip','encoding':'base64','media_type':'application/zip',
        'content':base64.b64encode(content).decode(),'sha256':sha256(content).hexdigest(),
        'configuration_sha256':sha256(json.dumps(configuration,sort_keys=True,separators=(',', ':')).encode()).hexdigest()}


def test_native_export_remains_an_optional_driver_capability():
    class Profile:
        def describe(self): return {'layout_export_supported':True}
        def export_layout(self,configuration): return artifact(configuration)
    class Discovery:
        def discover(self): return {'vendor':Profile()}, ()
    interactor=DeviceProfileInteractor(Discovery())
    assert interactor.export_layout('absent',{}) is None
    assert interactor.export_layout('vendor',{'track':'1'}) == artifact({'track':'1'})


@pytest.mark.parametrize('field,value', [('name','../escape.zip'), ('sha256','wrong'),
    ('content','!'), ('configuration_sha256','old-layout'), ('media_type','text/plain')])
def test_invalid_driver_archive_is_rejected_by_os_not_only_ui(field,value):
    data=artifact({'track':'1'});data[field]=value
    with pytest.raises(LayoutExportError):
        DeviceProfileInteractor(None).validate_layout_archive(data,{'track':'1'})
