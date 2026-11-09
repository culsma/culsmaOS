"""Instrument preflight checks using real OS contracts and concrete services."""
from dataclasses import replace
import pytest
from culsma_os.device_manager.models import DeviceConfigurationSnapshot
from culsma_os.device_manager.instruments.execution import InstrumentExecutionRouterInteractor
from culsma_os.device_manager.instruments.execution_models import ThermalHoldIntent, OrbitalShakeIntent, CentrifugeIntent, CentrifugeSeparationIntent
from culsma_os.device_manager.instruments.magnet.models import MagneticSeparationIntent
from culsma_os.device_manager.instruments.magnet.interactors import MagnetExecutionPreparationInteractor
from culsma_os.device_manager.instruments.temperature.interactors import TemperatureExecutionPreparationInteractor
from culsma_os.device_manager.instruments.shaker.interactors import ShakerExecutionPreparationInteractor
from culsma_os.device_manager.instruments.incubator.interactors import IncubatorExecutionPreparationInteractor
from culsma_os.device_manager.instruments.centrifuge.interactors import CentrifugeExecutionPreparationInteractor, CentrifugeMethodBindingInteractor
from culsma_os.workspace_manager.models import ResolvedContainerRef, SpaceBinding, LayoutSnapshot


def inputs():
    target=ResolvedContainerRef('sample')
    layout=LayoutSnapshot('run','layout',(SpaceBinding(target,'plate','A1',2200,'alloc'),))
    snapshot=DeviceConfigurationSnapshot('device','simulation','config',(),processing_capabilities={
        'thermal_hold':{'thermal':{'labware':['plate'],'temperature_range_celsius':[25,50]}},
        'orbital_shake':{'shaker':{'labware':['plate']}},
        'centrifuge':{'spin':{'labware':['plate'],'method_profiles':{
            'centrifuge_program':{'profile_id':'gentle','revision':'r1','duration_seconds':3}}}},
        'magnetic_separation':{'magnet':{'labware':['plate']}}})
    entries={'thermal_hold':TemperatureExecutionPreparationInteractor(None),
        'orbital_shake':ShakerExecutionPreparationInteractor(None),
        'centrifuge':CentrifugeExecutionPreparationInteractor(None,method_binding=CentrifugeMethodBindingInteractor()),
        'magnetic_separation':MagnetExecutionPreparationInteractor(None)}
    router=InstrumentExecutionRouterInteractor(entries, {('thermal_hold', 'incubator'): IncubatorExecutionPreparationInteractor(None)})
    return target,layout,snapshot,router


@pytest.mark.parametrize('capability,make_intent',[
    ('thermal_hold',lambda t:ThermalHoldIntent('heat',(t,),37,2)),
    ('orbital_shake',lambda t:OrbitalShakeIntent('shake',(t,),500,2)),
    ('centrifuge',lambda t:CentrifugeIntent('spin',(t,),250,'g',2)),
    ('magnetic_separation',lambda t:MagneticSeparationIntent('separate',(t,),5)),
])
def test_each_operation_selects_its_concrete_device_entry(capability,make_intent):
    target,layout,snapshot,router=inputs();intent=make_intent(target)
    entry,_=router.select(intent,layout,snapshot)
    assert entry is router.preparers[capability]
    assert router.bind_intent(intent,layout,snapshot)[0]==intent
    extra=replace(layout.bindings[0],reference=ResolvedContainerRef('other'),well='A2')
    with pytest.raises(ValueError,match='PROCESSING_COLLATERAL_EXPOSURE'):
        router.bind_intent(intent,replace(layout,bindings=(*layout.bindings,extra)),snapshot)
    with pytest.raises(ValueError,match='PROCESSING_MODULE_UNAVAILABLE'):
        router.bind_intent(intent,layout,replace(snapshot,processing_capabilities={}))

    declared = {capability: (capability,)}
    configured = snapshot.processing_capabilities[capability]
    cases = (
        ({}, {}, 'INSTRUMENT_DRIVER_UNAVAILABLE'),
        (declared, {}, 'INSTRUMENT_DEVICE_NOT_CONFIGURED'),
        (declared, {name: {**module, 'connection_state': 'disconnected'} for name, module in configured.items()},
         'INSTRUMENT_DEVICE_DISCONNECTED'),
        (declared, {name: {**module, 'labware': ['other']} for name, module in configured.items()},
         'PROCESSING_LABWARE_UNSUPPORTED'),
    )
    for drivers, modules, code in cases:
        current = replace(snapshot, instrument_drivers=drivers, processing_capabilities={capability: modules})
        with pytest.raises(ValueError, match=code):
            router.bind_intent(intent, layout, current)
    current = replace(snapshot, instrument_drivers=declared)
    assert router.bind_intent(intent, layout, current)[0] == intent


def test_incubator_is_selected_from_declared_device_capability():
    target,layout,snapshot,router=inputs()
    snapshot=replace(snapshot,processing_capabilities={'thermal_hold':{
        'cytomat':{'labware':['plate'],'instrument_kind':'incubator','temperature_range_celsius':[25,50]}}})
    intent=ThermalHoldIntent('incubate',(target,),37,2)
    assert isinstance(router.select(intent,layout,snapshot)[0], IncubatorExecutionPreparationInteractor)
    assert router.bind_intent(intent,layout,snapshot)[1]=='cytomat'
    with pytest.raises(ValueError,match='PROCESSING_TEMPERATURE_UNSUPPORTED'):
        router.bind_intent(replace(intent,temperature_celsius=60),layout,snapshot)


@pytest.mark.parametrize('rate',[199,3001,500.5])
def test_shaker_bounds_and_fractional_rates_are_rejected(rate):
    target,layout,snapshot,router=inputs()
    with pytest.raises(ValueError,match='PROCESSING_AGITATION_RATE_UNSUPPORTED'):
        router.bind_intent(OrbitalShakeIntent('shake',(target,),rate,2),layout,snapshot)


def test_centrifuge_method_fills_only_missing_duration_not_explicit_program_duration():
    target,layout,snapshot,router=inputs()
    result,_=router.bind_intent(CentrifugeSeparationIntent('sep',(target,),250,'g'),layout,snapshot)
    assert result.duration_seconds==3 and result.method_profile.revision=='r1'
    explicit=CentrifugeIntent('spin',(target,),250,'g',7)
    assert router.bind_intent(explicit,layout,snapshot)[0] is explicit
