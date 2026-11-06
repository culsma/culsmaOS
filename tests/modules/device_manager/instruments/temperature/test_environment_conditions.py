"""Device declarations decide gas/humidity support before any preparation."""
from dataclasses import replace
import pytest
from culsma_os.device_manager.instruments.execution_models import ThermalHoldIntent,EnvironmentCondition
from culsma_os.device_manager.instruments.temperature.interactors import TemperatureExecutionPreparationInteractor
from culsma_os.workspace_manager.models import ResolvedContainerRef


def intent(conditions):
    return ThermalHoldIntent('hold',(ResolvedContainerRef('sample'),),37,2,environment_conditions=conditions)


def test_supported_condition_is_admitted_and_missing_capability_rejects():
    request=intent((EnvironmentCondition('co2',5,'%'),))
    service=TemperatureExecutionPreparationInteractor(None)
    service.validate_intent(request,{'temperature_range_celsius':[25,50],
        'environment_conditions':{'co2':{'unit':'%','minimum':0,'maximum':100}}})
    with pytest.raises(ValueError,match='PROCESSING_ENVIRONMENT_CONDITION_UNSUPPORTED'):
        service.validate_intent(request,{'temperature_range_celsius':[25,50]})


@pytest.mark.parametrize('conditions',[
    (EnvironmentCondition('co2',101,'%'),),(EnvironmentCondition('co2',True,'%'),),
    (EnvironmentCondition('co2',float('nan'),'%'),),(EnvironmentCondition('co2',5,'ppm'),),
    (EnvironmentCondition('pressure',5,'bar'),),
    (EnvironmentCondition('co2',5,'%'),EnvironmentCondition('co2',6,'%'))])
def test_invalid_or_duplicate_conditions_never_pass_capability_checks(conditions):
    with pytest.raises(ValueError):
        TemperatureExecutionPreparationInteractor(None).validate_intent(intent(conditions),{
            'temperature_range_celsius':[25,50],
            'environment_conditions':{'co2':{'unit':'%','minimum':0,'maximum':100}}})
