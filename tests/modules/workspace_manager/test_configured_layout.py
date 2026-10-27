"""Current layout comes from the verified host, without opening a device session."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from culsma_os.workspace_manager.interactors import ConfiguredLayoutInteractor


class ConfigurationFixture:
    fingerprint = 'current'
    changed = False
    def verify(self, context):
        if self.changed: raise ValueError('HOST_CONFIGURATION_MISMATCH')


class LayoutReaderFixture:
    def __init__(self): self.calls=[]
    def execute(self, path):
        self.calls.append(path)
        return {'definition':{'schema':'culsma_layout_v1','variants':{}},'configuration':{'deck':'current'}}


def test_only_verified_current_layout_is_cached_and_results_are_detached():
    configuration,reader=ConfigurationFixture(),LayoutReaderFixture()
    context=SimpleNamespace(config_path=Path('/configured.json'),driver_name='external')
    view=ConfiguredLayoutInteractor(reader,configuration,context)
    result=view.execute()
    assert result['status']=='available' and result['configuration_fingerprint']=='current'
    result['layout']['configuration']['deck']='caller-edit'
    assert view.execute()['layout']['configuration']['deck']=='current'
    assert reader.calls==[context.config_path]
    configuration.changed=True
    with pytest.raises(ValueError,match='HOST_CONFIGURATION_MISMATCH'):view.execute()
    assert len(reader.calls)==1


def test_optional_layout_reader_and_invalid_projection_do_not_claim_availability():
    configuration=ConfigurationFixture();context=SimpleNamespace(config_path=None,driver_name='external')
    assert ConfiguredLayoutInteractor(None,configuration,context).execute()['status']=='unsupported'
    reader=SimpleNamespace(execute=lambda path:{'definition':{},'configuration':{},'agent':{'token':'secret'}})
    with pytest.raises(ValueError,match='CONFIGURED_LAYOUT_RESPONSE_INVALID'):
        ConfiguredLayoutInteractor(reader,configuration,context).execute()


def test_older_plugin_without_the_optional_reader_can_still_start(monkeypatch):
    import builtins
    from culsma_os.bootstrap import OpentronsSessionFactory
    original=builtins.__import__
    def importing(name,*args,**kwargs):
        if name=='culsma_opentrons.layout.interactors': raise ImportError('Older installed plugin')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',importing)
    assert OpentronsSessionFactory().build_layout_reader() is None
