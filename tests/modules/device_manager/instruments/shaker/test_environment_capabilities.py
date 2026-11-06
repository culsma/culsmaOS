"""Shaking limits and environment support belong to the selected instrument."""
import pytest
from culsma_os.device_manager.instruments.execution_models import OrbitalShakeIntent, EnvironmentCondition
from culsma_os.device_manager.instruments.shaker.interactors import ShakerExecutionPreparationInteractor


def test_selected_driver_controls_rate_and_environment_limits():
    intent = OrbitalShakeIntent('shake', (), 100, 30, (EnvironmentCondition('thermal',37,'C'),))
    capability = {'rate_range_rpm':[100,2500],
        'environment_conditions':{'thermal':{'unit':'C','minimum':25,'maximum':95}}}
    ShakerExecutionPreparationInteractor(None).validate_intent(intent, capability)
    with pytest.raises(ValueError, match='ENVIRONMENT_CONDITION_UNSUPPORTED'):
        ShakerExecutionPreparationInteractor(None).validate_intent(intent, {'rate_range_rpm':[100,2500]})


@pytest.mark.parametrize('limits', [[3000,200], [100], [float('nan'),3000], [True,3000]])
def test_invalid_driver_rate_bounds_are_rejected(limits):
    with pytest.raises(ValueError, match='CAPABILITY_INVALID'):
        ShakerExecutionPreparationInteractor(None).validate_intent(OrbitalShakeIntent('shake', (),500,30),
            {'rate_range_rpm':limits})


@pytest.mark.parametrize('rate', [99,2501,500.5,True])
def test_outside_selected_driver_range_is_rejected(rate):
    with pytest.raises(ValueError, match='RATE_UNSUPPORTED'):
        ShakerExecutionPreparationInteractor(None).validate_intent(OrbitalShakeIntent('shake', (),rate,30),
            {'rate_range_rpm':[100,2500]})



def test_unspecified_motion_requires_selected_device_default():
    intent = OrbitalShakeIntent('shake', (), 200, 30, requires_motion_default=True)
    shaker = ShakerExecutionPreparationInteractor(None)
    for capability in ({}, {'default_motion': 'linear'}):
        with pytest.raises(ValueError, match='PROCESSING_AGITATION_MOTION_DEFAULT_REQUIRED'):
            shaker.validate_intent(intent, capability)
    shaker.validate_intent(intent, {'default_motion': 'orbital'})
