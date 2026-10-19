import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.workspace_manager.models import ConfigurationError, StationConfigurationRequest
from tests.support.workspace_manager.configuration import ConfigurationFixture


def create(fixture, configuration=None):
    return fixture.execute(StationConfigurationRequest('create',title='Station',driver='test-profile',
        configuration=configuration or {'valid':True}))['draft']


def test_unauthorized_draft_request_creates_nothing(tmp_path):
    path = tmp_path/'absent'/'drafts.sqlite3';fixture = ConfigurationFixture(path)
    for token in [None,'Bearer forged','',fixture.credential+'x']:
        with pytest.raises(ConsoleAccessError):
            fixture.interactor.execute(token,StationConfigurationRequest('list'))
    assert not path.parent.exists()


def test_stale_revision_preserves_saved_draft(tmp_path):
    fixture = ConfigurationFixture(tmp_path/'drafts.sqlite3');first = create(fixture)
    second = fixture.execute(StationConfigurationRequest('save',first['draft_id'],1,'Changed','test-profile',{'valid':False}))['draft']
    assert second['revision']==2
    with pytest.raises(ConfigurationError,match='CONFIGURATION_REVISION_CONFLICT'):
        fixture.execute(StationConfigurationRequest('save',first['draft_id'],1,'Stale','test-profile',{'valid':True}))
    assert fixture.execute(StationConfigurationRequest('get',first['draft_id']))['draft'] == second
    assert fixture.execute(StationConfigurationRequest('get',first['draft_id'],1))['draft'] == first
    with pytest.raises(ConfigurationError,match='CONFIGURATION_REVISION_CONFLICT'):
        fixture.execute(StationConfigurationRequest('export',first['draft_id'],1))


def test_concurrent_updates_have_one_winner(tmp_path):
    fixture = ConfigurationFixture(tmp_path/'drafts.sqlite3');draft = create(fixture)
    def save(title):
        try:
            return fixture.execute(StationConfigurationRequest('save',draft['draft_id'],1,title,'test-profile',{'valid':True}))
        except ConfigurationError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save,['First','Second']))
    assert sum(isinstance(value,dict) for value in results)==1
    assert results.count('CONFIGURATION_REVISION_CONFLICT')==1


def test_invalid_draft_cannot_export(tmp_path):
    fixture = ConfigurationFixture(tmp_path/'drafts.sqlite3');draft = create(fixture,{'valid':False})
    result = fixture.execute(StationConfigurationRequest('validate',draft['draft_id'],1))
    assert result['validation']['valid'] is False and result['activation']=='not_applied'
    with pytest.raises(ConfigurationError,match='CONFIGURATION_EXPORT_INVALID'):
        fixture.execute(StationConfigurationRequest('export',draft['draft_id'],1))


def test_draft_roundtrip_export_preserves_exact_values(tmp_path):
    fixture = ConfigurationFixture(tmp_path/'drafts.sqlite3')
    configuration={'valid':True,'nested':{'future_setting':[1,'two',None]},'number':3.0}
    draft=create(fixture,configuration)
    configuration['nested']['future_setting'].append('mutated caller')
    exported=fixture.execute(StationConfigurationRequest('export',draft['draft_id'],1))
    assert exported['configuration']==draft['configuration']
    assert exported['fingerprint']==draft['fingerprint'] and exported['activation']=='not_applied'
    stored=fixture.repository.list()[0]
    assert stored.as_dict()==draft
    detached=stored.as_dict();detached['configuration']['nested']['future_setting'].append('detached')
    assert stored.as_dict()==draft


@pytest.mark.parametrize('draft_request',[
    StationConfigurationRequest('activate'),
    StationConfigurationRequest('create',title='x',driver='test-profile',configuration={'number':float('nan')}),
    StationConfigurationRequest('create',title='x',driver='../driver',configuration={}),
    StationConfigurationRequest('get','../private'),
    StationConfigurationRequest('get','id',True),
])
def test_invalid_requests_are_rejected_before_draft_write(tmp_path,draft_request):
    path=tmp_path/'drafts.sqlite3';fixture=ConfigurationFixture(path)
    with pytest.raises(ConfigurationError): fixture.execute(draft_request)
    assert not path.exists()
