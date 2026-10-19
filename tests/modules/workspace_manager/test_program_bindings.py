from dataclasses import replace
import pytest
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.workspace_manager.models import ConfigurationError
from tests.support.workspace_manager.bindings import ProgramBindingFixture


@pytest.fixture
def bindings(tmp_path): return ProgramBindingFixture(tmp_path)


def test_binding_review_requires_authentication(bindings,monkeypatch):
    def forbidden(*args): raise AssertionError('Unauthenticated owner access')
    monkeypatch.setattr(bindings.repository,'get',forbidden)
    monkeypatch.setattr(bindings.programs.source_interactor,'review',forbidden)
    monkeypatch.setattr(bindings.profiles,'validate',forbidden)
    with pytest.raises(ConsoleAccessError): bindings.interactor.execute(None,bindings.request)


def test_binding_review_pins_saved_revision_and_snapshot(bindings):
    before = bindings.repository.list()
    bindings.programs.source.write_text('changed original source')
    report = bindings.execute()
    assert report['valid'] and report['activation']=='not_applied'
    assert report['revision']==1 and report['snapshot_id']==bindings.snapshot.snapshot_id
    assert [row['name'] for row in report['bindings']]==['source','destination']
    assert all(row['status']=='matched' for row in report['bindings'])
    assert 'worker preflight' in report['scope']
    assert before==bindings.repository.list() and not bindings.programs.calls


def test_binding_review_rejects_stale_revision(bindings,monkeypatch):
    bindings.save(bindings.configuration)
    def forbidden(*args): raise AssertionError('Stale review compiled source')
    monkeypatch.setattr(bindings.programs.source_interactor,'review',forbidden)
    with pytest.raises(ConfigurationError,match='CONFIGURATION_REVISION_CONFLICT'): bindings.execute()


def test_binding_review_rechecks_revision_after_compilation(bindings,monkeypatch):
    original = bindings.programs.source_interactor.review
    def review(*args):
        result=original(*args);bindings.save(bindings.configuration);return result
    monkeypatch.setattr(bindings.programs.source_interactor,'review',review)
    with pytest.raises(ConfigurationError,match='CONFIGURATION_REVISION_CONFLICT'): bindings.execute()


def test_binding_review_reports_missing_and_extra_allocations(bindings):
    raw=bindings.configuration
    raw['bindings']['unexpected']=raw['bindings'].pop('entry.s1::alloc')
    bindings.save(raw)
    report=bindings.execute(replace(bindings.request,revision=2))
    assert not report['valid']
    assert {d['code'] for d in report['diagnostics']}=={'CONFIGURATION_BINDING_MISSING','CONFIGURATION_BINDING_EXTRA'}
    assert len(report['bindings'])==3


def test_binding_review_reports_duplicate_addresses(bindings):
    raw=bindings.configuration
    raw['bindings']['entry.s1::alloc']=raw['bindings']['entry.s0::alloc'].copy()
    bindings.save(raw)
    report=bindings.execute(replace(bindings.request,revision=2))
    assert not report['valid'] and report['diagnostics'][0]['code']=='CONFIGURATION_BINDING_DUPLICATE'


@pytest.mark.parametrize('owner',['program','configuration'])
def test_binding_review_rejects_source_and_configuration_errors(bindings,owner):
    request=bindings.request
    if owner=='program':
        bindings.programs.source.write_text('not a program !')
        request=replace(request,snapshot_id=bindings.programs.sources.capture().snapshot_id)
    else:
        bindings.save({**bindings.configuration,'valid':False});request=replace(request,revision=2)
    report=bindings.execute(request)
    assert not report['valid'] and report['bindings']==[]
    assert report['diagnostics'][0]['owner']==owner
    assert not bindings.programs.calls


def test_binding_review_requires_optional_offline_capability(bindings,monkeypatch):
    monkeypatch.setattr(bindings.profiles,'program_bindings',lambda *args:None)
    assert bindings.execute()['diagnostics'][0]['code']=='CONFIGURATION_BINDINGS_UNAVAILABLE'


@pytest.mark.parametrize('raw',[[],{'x':{'labware':'tubes'}},{'x':{'labware':1,'well':'A1'}}])
def test_malformed_profile_projection_is_not_accepted(bindings,monkeypatch,raw):
    monkeypatch.setattr(bindings.profiles,'program_bindings',lambda *args:raw)
    with pytest.raises(ConfigurationError,match='CONFIGURATION_BINDINGS_RESPONSE_INVALID'):bindings.execute()


@pytest.mark.parametrize('change',[{'revision':True},{'revision':0},{'snapshot_id':'bad'},{'draft_id':'../x'},{'program_id':''}])
def test_binding_review_validates_identity_types(bindings,change):
    with pytest.raises(ConfigurationError):bindings.execute(replace(bindings.request,**change))
