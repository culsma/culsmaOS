from culsma_os.driver_framework.interactors import DriverProfileInteractor
from culsma_os.device_manager.interactors import DeviceProfileInteractor


class Profile:
    def describe(self):return {'label':'External profile'}
    def validate(self,configuration):return {'valid':True,'diagnostics':[],'scope':'static only'}


class Factory:
    def configuration_profile(self):return Profile()


class Entry:
    name='external'
    def load(self):return Factory


def test_external_profiles_are_discovered_without_device_sessions():
    interactor=DeviceProfileInteractor(DriverProfileInteractor([Entry()]))
    assert interactor.describe()['profiles']==[{'driver':'external','label':'External profile'}]
    assert interactor.validate('external',{})['valid']
    assert not interactor.validate('missing',{})['valid']


def test_duplicate_profiles_are_unavailable_instead_of_selected_arbitrarily():
    result=DeviceProfileInteractor(DriverProfileInteractor([Entry(),Entry()])).describe()
    assert result['profiles']==[] and result['unavailable']==['external']


def test_offline_bindings_are_optional_for_existing_plugins():
    interactor=DeviceProfileInteractor(DriverProfileInteractor([Entry()]))
    assert interactor.program_bindings('external',{}) is None
    assert interactor.program_bindings('missing',{}) is None
