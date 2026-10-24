"""Loading-plan generation preserves existing vendor-neutral motion routes."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from culsma_os.program_manager.interactors.setup import RunSetupInteractor


@pytest.mark.parametrize('workspace', [None, {}, {'routes': {}}, {'routes': {'step': [{'labware':'plate','destination':'module:spin'}]}}])
def test_setup_routes_preserve_override_and_do_not_alias_checkpoint_or_device(workspace):
    configured={'legacy': [{'labware':'plate','destination':'deck'}]}
    snapshot=SimpleNamespace(motion_capabilities={'before_steps': configured})
    setup=RunSetupInteractor(None,None,None,None,None,None,None,None,snapshot,None,None,None,None)
    data={'workspace': workspace}
    original=deepcopy(data)
    expected=(workspace or {}).get('routes',configured)
    selected=setup.routes_for_setup(data)
    assert selected==expected
    selected['extra']=[]
    assert data==original and 'extra' not in configured


def test_no_motion_capability_keeps_existing_route_free_loading_behavior():
    snapshot=SimpleNamespace(motion_capabilities={})
    setup=RunSetupInteractor(None,None,None,None,None,None,None,None,snapshot,None,None,None,None)
    assert setup.routes_for_setup({})=={}


def test_loading_confirmation_is_invalidated_when_checkpoint_routes_change():
    routes={'step':[{'labware':'plate','destination':'module:spin'}]}
    data={'plan_fingerprint':'plan','initial_fingerprint':'initial','workspace':{'bindings':{},'routes': routes}}
    identity={'plan':'plan','initial':'initial','configuration':'config','catalogue':'hash'}
    value={'fingerprint':'hash','identity':identity,'bindings':{},'routes':deepcopy(routes),'revision':1,'phase':'planned','confirmation':None}
    codec=SimpleNamespace(loads=lambda _:data,fingerprint=lambda _:'hash')
    setup=RunSetupInteractor(SimpleNamespace(get=lambda _:deepcopy(value)),
        SimpleNamespace(get=lambda _:SimpleNamespace(checkpoint='checkpoint')),None,None,codec,None,None,{},
        SimpleNamespace(configuration_revision='config'),None,None,None,None)
    assert setup.validate('run','hash')['routes']==routes
    data['workspace']['routes']={}
    with pytest.raises(ValueError,match='SETUP_PLAN_STALE'):
        setup.validate('run','hash')
