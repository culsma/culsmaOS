from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pytest
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.device_manager.instruments.models import ModuleProfileError
from culsma_os.device_manager.instruments.profile_api_models import InstrumentProfileRequest
from culsma_os.device_manager.instruments.sqlite_repository import FileModuleProfileRepository
from culsma_os.driver_framework.interactors import DriverInstrumentMethodInteractor
from culsma_os.workspace_manager.models import StationConfigurationRequest
from tests.support.device_manager.profile_api import ProfileAPIFixture


@pytest.fixture
def profiles(tmp_path): return ProfileAPIFixture(tmp_path)


def test_catalogue_has_real_modules_constraints_and_no_writes(profiles):
    result = profiles.owner.execute(profiles.credential, InstrumentProfileRequest('catalogue', **profiles.context))
    assert {m['kind'] for m in result['modules']} == {'magnet', 'pipetting'}
    definition = next(d for d in result['methods'] if d['module']['kind'] == 'pipetting')
    assert definition['parameter_schema']['properties']['aspiration_height_mm']['unit'] == 'mm'
    assert definition['parameter_schema']['additionalProperties'] is False
    assert not profiles.profiles.path.exists()
    assert result['activation'] == 'not_applied' and result['run_binding'] == 'not_bound'


def test_validate_save_read_and_append_preserve_exact_old_version(profiles):
    owner, raw = profiles.owner, profiles.credential
    request = InstrumentProfileRequest('validate', **profiles.values)
    assert owner.execute(raw, request)['valid']
    assert not profiles.profiles.path.exists()
    first = owner.execute(raw, replace(request, action='save'))['profile']
    second = owner.execute(raw, replace(request, action='save', expected_revision=first['reference']['revision'],
        parameters={**profiles.values['parameters'], 'aspiration_height_mm': 6.0}))['profile']
    read = InstrumentProfileRequest('read', first['reference']['device_id'], first['reference']['module_id'],
        profile_id=first['reference']['profile_id'], profile_revision=first['reference']['revision'])
    assert owner.execute(raw, read)['profile'] == first
    assert owner.execute(raw, replace(read, profile_revision=second['reference']['revision']))['profile'] == second
    assert len(owner.execute(raw, replace(read, action='list'))['profiles']) == 2
    assert profiles.repository.get(profiles.draft['draft_id']).as_dict() == profiles.draft
    reopened = FileModuleProfileRepository(profiles.profiles.path)
    assert len(reopened.list_profiles(read.device_id, read.module_id)) == 2
    with pytest.raises(ModuleProfileError, match='PROFILE_REVISION_CONFLICT'):
        owner.execute(raw, replace(request, action='save'))
    with pytest.raises(ModuleProfileError, match='PROFILE_REVISION_NOT_FOUND'):
        owner.execute(raw, replace(read, profile_revision='missing'))


@pytest.mark.parametrize('parameters', [
    {'aspiration_height_mm': -1, 'dispense_height_mm': 5, 'liquid_class': 'x'},
    {'flow_rate': 5}, {}, {'aspiration_height_mm': float('nan')},
])
def test_rejected_parameters_never_persist(profiles, parameters):
    request = InstrumentProfileRequest('validate', **{**profiles.values, 'parameters': parameters})
    if 'aspiration_height_mm' in parameters and str(parameters['aspiration_height_mm']) == 'nan':
        with pytest.raises(ModuleProfileError): profiles.owner.execute(profiles.credential, request)
    else:
        result = profiles.owner.execute(profiles.credential, request)
        assert result['valid'] is False and result['diagnostics']
    with pytest.raises(ModuleProfileError): profiles.owner.execute(profiles.credential, replace(request, action='save'))
    assert not profiles.profiles.path.exists()


def test_auth_runs_before_discovery_and_storage(profiles):
    request = InstrumentProfileRequest('save', **profiles.values)
    with pytest.raises(ConsoleAccessError): profiles.owner.execute('Bearer invalid', request)
    renderer = 'Bearer ' + profiles.tokens.issue_renderer_session()
    with pytest.raises(ConsoleAccessError, match='CONSOLE_CAPABILITY_DENIED'):
        profiles.owner.execute(renderer, request)
    assert not profiles.profiles.path.exists()


def test_missing_module_stale_definition_and_unsupported_driver(profiles):
    for changes, code in [({'module_id': 'missing'}, 'PROFILE_MODULE_UNAVAILABLE'),
                          ({'definition_revision': 'old'}, 'PROFILE_DEFINITION_STALE')]:
        request = InstrumentProfileRequest('save', **{**profiles.values, **changes})
        with pytest.raises(ModuleProfileError, match=code): profiles.owner.execute(profiles.credential, request)
    with pytest.raises(ModuleProfileError, match='PROFILE_DRIVER_UNAVAILABLE'):
        DriverInstrumentMethodInteractor([]).for_configuration('missing', {}, '1')
    from importlib.metadata import EntryPoint
    candidate = EntryPoint(name='offline-layout', value='culsma_driver_hamilton.assembly:build_configuration_profile', group='culsma.os_devices')
    with pytest.raises(ModuleProfileError, match='INSTRUMENT_PROFILES_UNSUPPORTED'):
        DriverInstrumentMethodInteractor([candidate]).for_configuration('offline-layout', {}, '1')
    assert not profiles.profiles.path.exists()


def test_exact_saved_configuration_does_not_drift_to_latest(profiles):
    config = {**profiles.configuration, 'device_id': 'other-device'}
    profiles.configurations.execute(profiles.credential, StationConfigurationRequest('save', profiles.draft['draft_id'],
        1, 'Changed', 'hamilton-local', config))
    request = InstrumentProfileRequest('catalogue', **profiles.context)
    result = profiles.owner.execute(profiles.credential, request)
    assert result['configuration']['revision'] == 1
    assert all(m['device_id'] == profiles.context['device_id'] for m in result['modules'])
    with pytest.raises(ModuleProfileError, match='PROFILE_DEVICE_MISMATCH'):
        profiles.owner.execute(profiles.credential, replace(request, configuration_revision=2))


def test_two_writers_from_same_revision_only_one_succeeds(profiles):
    request = InstrumentProfileRequest('save', **profiles.values)
    first = profiles.owner.execute(profiles.credential, request)['profile']
    update = replace(request, expected_revision=first['reference']['revision'])
    def save():
        try: return profiles.owner.execute(profiles.credential, update)['profile']['reference']['revision']
        except ModuleProfileError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: save(), range(2)))
    assert results.count('PROFILE_REVISION_CONFLICT') == 1
    assert len(profiles.profiles.list_profiles(request.device_id, request.module_id)) == 2
