"""OS contracts use a vendor-neutral fake; no concrete driver dependency."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import ResidentCommand
from culsma_os.workspace_manager.models import LabwareRequest, ConfigurationError
from culsma_os.workspace_manager.interactors import ResidentLabwareInteractor, LabwareConfigurationInteractor
from culsma_os.workspace_manager.repositories.configuration import SqliteStationConfigurationRepository


class Configuration:
    fingerprint='a'*64
    def verify(self, context): pass


class Editor:
    def __init__(self): self.calls=[]
    def catalogue(self, path):
        self.calls.append('catalogue')
        return {'schema':'culsma_labware_catalogue_v1','models':[{'id':'plate','label':'A plate','category':'plate'}],
                'targets':[{'id':'slot1','label':'Slot 1','parent':'rack','site':'1','occupants':[],'models':['plate'],'reason':None}]}
    def prepare(self, path, change):
        self.calls.append('prepare')
        return {'configuration':{'selected':'plate','connection':'private fixture'},'layout':{'definition':{},'configuration':{}}}


def test_os_port_does_not_require_vendor_objects_and_checks_staleness():
    editor=Editor();owner=ResidentLabwareInteractor(editor,Configuration(),SimpleNamespace(config_path='config',driver_name='external'))
    with pytest.raises(ValueError,match='STALE'):
        owner.execute(ResidentCommand('labware-catalogue',configuration_fingerprint='b'*64))
    assert not editor.calls
    result=owner.execute(ResidentCommand('labware-catalogue',configuration_fingerprint='a'*64))
    assert result['driver']=='external' and result['catalogue']['targets'][0]['models']==['plate']
    malformed=deepcopy(result['catalogue']);malformed['targets'][0]['models']=['unknown']
    with pytest.raises(ValueError,match='CATALOGUE_INVALID'): owner.validate_catalogue(malformed)
    malformed=deepcopy(result['catalogue']);malformed['models']*=2
    with pytest.raises(ValueError,match='CATALOGUE_INVALID'): owner.validate_catalogue(malformed)


def test_preparation_requires_credential_and_hides_full_configuration(tmp_path):
    tokens=TokenInteractor(SessionCredentialRepository())
    repository=SqliteStationConfigurationRepository(tmp_path/'drafts.sqlite3')
    editor=Editor();owner=ResidentLabwareInteractor(editor,Configuration(),SimpleNamespace(config_path='config',driver_name='external'))
    class Resident:
        def execute(self, payload):
            return owner.execute(ResidentCommand(payload['action'],configuration_fingerprint=payload['configuration_fingerprint'],labware_change=payload['labware_change']))
    subject=LabwareConfigurationInteractor(tokens,repository,Resident())
    request=LabwareRequest('prepare','a'*64,{'action':'place','target':'slot1','name':'plate1','model':'plate'})
    with pytest.raises(ConsoleAccessError): subject.execute(None,request)
    assert not editor.calls
    result=subject.execute('Bearer '+tokens.issue_console_session(),request)
    assert set(result['draft'])=={'draft_id','revision','title','driver','fingerprint'}
    assert 'private fixture' not in str(result) and result['activation']=='not_applied'
    assert repository.get(result['draft']['draft_id']).as_dict()['configuration']['selected']=='plate'
    with pytest.raises(ConsoleAccessError): subject.execute('Bearer '+tokens.issue_automation_session(),request)


@pytest.mark.parametrize('invalid_request',[
    LabwareRequest('prepare','a'*64,{'action':'place','target':'s','credential':'bad'}),
    LabwareRequest('catalogue','bad'),
    LabwareRequest('catalogue','a'*64,{}),
    LabwareRequest('prepare','a'*64,None),
])
def test_invalid_requests_never_reach_resident(tmp_path,invalid_request):
    tokens=TokenInteractor(SessionCredentialRepository())
    class Resident:
        def execute(self,payload): raise AssertionError('Invalid input reached resident')
    subject=LabwareConfigurationInteractor(tokens,SqliteStationConfigurationRepository(tmp_path/'drafts.sqlite3'),Resident())
    with pytest.raises(ConfigurationError): subject.execute('Bearer '+tokens.issue_console_session(),invalid_request)


def test_driver_carrier_metadata_is_validated_before_presentation():
    owner=ResidentLabwareInteractor(Editor(),Configuration(),SimpleNamespace())
    catalogue={'schema':'culsma_labware_catalogue_v1','models':[{'id':'rack','label':'Rack','category':'carrier'}],
        'targets':[{'id':'rack1','kind':'carrier','label':'Rack 1','parent':'deck','site':'1','occupants':['rack1'],
                    'models':['rack'],'reason':None,'current_model':'rack','span':2,'contents':[],'blocked_models':[]}]}
    owner.validate_catalogue(catalogue)
    for field,value in [('kind',[]),('contents','bad'),('span',True),('blocked_models',[{'id':'unknown','reason':'bad'}])]:
        bad=deepcopy(catalogue);bad['targets'][0][field]=value
        with pytest.raises(ValueError,match='CATALOGUE_INVALID'):owner.validate_catalogue(bad)
