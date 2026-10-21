from copy import deepcopy
import pytest
from culsma_os.workspace_manager.models import ConfigurationError, StationConfigurationRequest
from tests.support.workspace_manager.configuration import ConfigurationFixture


class ExportingProfile:
    def __init__(self): self.calls = []
    def validate(self, driver, configuration):
        return {'valid': configuration['valid'], 'diagnostics': []}
    def export_layout(self, driver, configuration):
        self.calls.append((driver, deepcopy(configuration)))
        return {'encoding': 'base64', 'content': 'UEs=', 'configuration_sha256': 'fixture'}


def create(fixture):
    return fixture.execute(StationConfigurationRequest('create', title='Layout',
        driver='test-profile', configuration={'valid': True, 'track': '16'}))['draft']


def test_export_uses_exact_saved_revision_without_applying_station(tmp_path):
    fixture = ConfigurationFixture(tmp_path/'drafts.sqlite3')
    profile = ExportingProfile(); fixture.interactor.profiles = profile
    draft = create(fixture)
    result = fixture.execute(StationConfigurationRequest('export_layout',draft['draft_id'],1))
    assert result['layout_artifact']['content'] == 'UEs='
    assert result['fingerprint'] == draft['fingerprint']
    assert result['configuration'] == draft['configuration']
    assert profile.calls == [('test-profile',draft['configuration'])]
    assert result['activation'] == 'not_applied'
    assert fixture.repository.get(draft['draft_id']).revision == 1


def test_stale_or_invalid_configuration_never_reaches_native_export(tmp_path):
    fixture = ConfigurationFixture(tmp_path/'drafts.sqlite3')
    profile = ExportingProfile(); fixture.interactor.profiles = profile
    draft = create(fixture)
    fixture.execute(StationConfigurationRequest('save',draft['draft_id'],1,'Invalid','test-profile',{'valid':False}))
    for revision,code in [(1,'CONFIGURATION_REVISION_CONFLICT'),(2,'CONFIGURATION_EXPORT_INVALID')]:
        with pytest.raises(ConfigurationError,match=code):
            fixture.execute(StationConfigurationRequest('export_layout',draft['draft_id'],revision))
    assert profile.calls == []


def test_driver_export_error_is_a_configuration_diagnostic(tmp_path):
    class FailedProfile(ExportingProfile):
        def export_layout(self, driver, configuration):
            raise ValueError('Internal vendor detail')
    fixture = ConfigurationFixture(tmp_path/'drafts.sqlite3')
    fixture.interactor.profiles = FailedProfile(); draft = create(fixture)
    with pytest.raises(ConfigurationError,match='CONFIGURATION_LAYOUT_EXPORT_FAILED'):
        fixture.execute(StationConfigurationRequest('export_layout',draft['draft_id'],1))
