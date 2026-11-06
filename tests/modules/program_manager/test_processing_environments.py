"""Normalize actual serialized language quantities without driver defaults."""
import pytest
from culsma_os.program_manager.interactors.processing_intents import ThermalHoldPreparationInteractor
from culsma_os.device_manager.instruments.execution_models import EnvironmentCondition


def test_normalize_all_declared_conditions_and_preserve_explicit_zero():
    env={name:{'kind':'IRQuantity','value':value,'unit':'%'} for name,value in [('co2',5),('o2',0),('humidity',50)]}
    before={name:dict(value) for name,value in env.items()}
    assert ThermalHoldPreparationInteractor().environment_conditions(env)==(
        EnvironmentCondition('co2',5.0,'%'),EnvironmentCondition('o2',0.0,'%'),EnvironmentCondition('humidity',50.0,'%'))
    assert env==before
    assert ThermalHoldPreparationInteractor().environment_conditions({})==()


@pytest.mark.parametrize('value',[-1,101,float('nan'),True])
def test_invalid_percentage_fails_before_device_selection(value):
    with pytest.raises(ValueError):
        ThermalHoldPreparationInteractor().environment_conditions({'co2':{'kind':'IRQuantity','value':value,'unit':'%'}})


@pytest.fixture
def heated_shake_pending(tmp_path):
    from culsma_os.program_manager.interactors.compilation import CompilationInteractor
    from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
    source = tmp_path / 'heated.culs'
    source.write_text('let sample=tube(capacity=2000uL,load=[content(kind=formulation,type=buffer,code="B"):100uL]);'
        'with env(thermal=37C,duration=30s) {'
        'agit(sample=sample,mode=shake,motion=orbital,duration=30s,rate=500rpm);}')
    compiled = CompilationInteractor().compile([source])
    host = HostedRuntimeInteractor()
    checkpoint = host.advance(host.create(compiled.plan, compiled.state, 'heated-shake'))
    pending = host.pending(checkpoint)
    assert pending.prepared.runtime_step.op == 'agit'
    return pending


def test_agitation_preserves_environment_from_real_language_step(heated_shake_pending):
    from culsma_os.program_manager.interactors.processing_intents import OrbitalShakePreparationInteractor
    result = OrbitalShakePreparationInteractor().resolve_intent(heated_shake_pending)
    assert result.environment_conditions == (EnvironmentCondition('thermal', 37, 'C'),)
    assert result.rate_rpm == 500 and result.duration_seconds == 30


@pytest.mark.parametrize('fault,code', [
    ('duration', 'DURATION_MISMATCH'), ('targets', 'TARGET_INVALID'),
    ('nested', 'ENVIRONMENT_UNSUPPORTED'), ('unknown', 'ENVIRONMENT_UNSUPPORTED')])
def test_agitation_rejects_environment_mismatch_before_driver(heated_shake_pending, fault, code):
    from copy import deepcopy
    from culsma_os.program_manager.interactors.processing_intents import OrbitalShakePreparationInteractor
    pending = deepcopy(heated_shake_pending)
    gate = pending.prepared.runtime_step.gate
    if fault == 'duration':
        gate['env']['duration'] = {'kind':'IRQuantity','value':60,'unit':'s'}
        gate['env_layers'][0]['env'] = deepcopy(gate['env'])
    elif fault == 'targets':
        gate['env_targets'] = []
        gate['env_layers'][0]['env_targets'] = []
    elif fault == 'nested':
        gate['env_layers'].append(deepcopy(gate['env_layers'][0]))
    else:
        gate['env']['unknown'] = 1
        gate['env_layers'][0]['env'] = deepcopy(gate['env'])
    with pytest.raises(ValueError, match=code):
        OrbitalShakePreparationInteractor().resolve_intent(pending)


def test_valid_environment_targets_must_equal_agitated_targets(heated_shake_pending):
    from culsma_os.program_manager.interactors.processing_intents import OrbitalShakePreparationInteractor
    with pytest.raises(ValueError, match='TARGETS_MISMATCH'):
        OrbitalShakePreparationInteractor().environment_conditions(heated_shake_pending, (), 30)
