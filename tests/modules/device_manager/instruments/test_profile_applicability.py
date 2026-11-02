"""Real immutable contracts and checks, without mocked devices or state."""
from dataclasses import replace
import pytest
from culsma_os.device_manager.instruments.applicability import (
    AspirationVolumeRange, ProfileApplicability, ProfileOperationContext, ProfileApplicabilityInteractor)
from culsma_os.device_manager.instruments.models import ModuleProfileError
from culsma_os.device_manager.instruments.pipetting.profile_parameters import PipettingParameters


def scope():
    return ProfileApplicability('magnetic_flowthrough_transfer', ('plate',), ('reservoir',),
        ('tips',), AspirationVolumeRange(10, 300), ('magnetically_held',))


def context():
    return ProfileOperationContext('run', 'step', 'magnetic_flowthrough_transfer',
        ('plate',), ('reservoir',), ('tips',), (300, 150), ('magnetically_held',))


def test_every_stroke_is_checked_and_endpoints_are_inclusive():
    check = ProfileApplicabilityInteractor()
    check.require_matching_operation(scope(), context(), 'run', 'step')
    check.require_matching_operation(scope(), replace(context(), aspiration_volumes_uL=(10, 300)), 'run', 'step')
    with pytest.raises(ModuleProfileError, match='PROFILE_ASPIRATION_VOLUME_MISMATCH'):
        check.require_matching_operation(scope(), replace(context(), aspiration_volumes_uL=(300, 9)), 'run', 'step')


@pytest.mark.parametrize('changes,code', [
    ({'run_id': 'other'}, 'CONTEXT_MISMATCH'),
    ({'step_id': 'other'}, 'CONTEXT_MISMATCH'),
    ({'operation': 'transfer', 'source_conditions': ()}, 'OPERATION_MISMATCH'),
    ({'source_models': ('wrong',)}, 'SOURCE_MODELS_MISMATCH'),
    ({'destination_models': ('wrong',)}, 'DESTINATION_MODELS_MISMATCH'),
    ({'tip_models': ('wrong',)}, 'TIP_MODELS_MISMATCH')])
def test_wrong_operation_facts_are_rejected(changes, code):
    with pytest.raises(ModuleProfileError, match=code):
        ProfileApplicabilityInteractor().require_matching_operation(scope(), replace(context(), **changes), 'run', 'step')


def test_scoped_profile_requires_context_and_source_condition():
    check = ProfileApplicabilityInteractor()
    with pytest.raises(ModuleProfileError, match='OPERATION_CONTEXT_REQUIRED'):
        check.require_matching_operation(scope(), None, 'run', 'step')
    transfer = ProfileApplicability('transfer', required_source_conditions=('magnetically_held',))
    with pytest.raises(ModuleProfileError, match='SOURCE_CONDITION_MISMATCH'):
        check.require_matching_operation(transfer, replace(context(), operation='transfer', source_conditions=()), 'run', 'step')
    check.require_matching_operation(None, None, 'run', 'step')


def test_json_roundtrip_has_no_hidden_inheritance_or_vendor_fields():
    import json
    check = ProfileApplicabilityInteractor()
    value = json.loads(json.dumps(check.encode(scope())))
    assert check.parse(value) == scope()
    assert check.parse(None) is None and check.encode(None) is None


@pytest.mark.parametrize('value', [[], {}, {'operation': []}, {'operation': 'unknown'},
    {'operation': 'transfer', 'native_liquid_class': 'x'},
    {'operation': 'transfer', 'source_models': 'plate'},
    {'operation': 'transfer', 'tip_models': [1]},
    {'operation': 'transfer', 'tip_models': ['t', 't']},
    {'operation': 'transfer', 'required_source_conditions': ['unknown']},
    {'operation': 'transfer', 'per_aspiration_volume_uL': {'minimum': 10}},
    {'operation': 'transfer', 'per_aspiration_volume_uL': {'minimum': True, 'maximum': 300}},
    {'operation': 'transfer', 'per_aspiration_volume_uL': {'minimum': 300, 'maximum': 10}},
    {'operation': 'magnetic_flowthrough_transfer'},
    {'operation': 'magnetic_separation', 'tip_models': ['tips']}])
def test_malformed_applicability_is_not_accepted(value):
    with pytest.raises(ModuleProfileError): ProfileApplicabilityInteractor().parse(value)


@pytest.mark.parametrize('values', [(0, 1), (-1, 1), (1, float('inf')), (float('nan'), 2)])
def test_ranges_are_finite_positive_and_ordered(values):
    with pytest.raises(ModuleProfileError): AspirationVolumeRange(*values)


@pytest.mark.parametrize('changes', [ {'aspiration_volumes_uL': (True,)},
    {'aspiration_volumes_uL': (float('nan'),)}, {'aspiration_volumes_uL': []},
    {'tip_models': ()}, {'source_models': ()}, {'run_id': ''}, {'source_conditions': ()}])
def test_context_requires_typed_complete_facts(changes):
    with pytest.raises(ModuleProfileError): replace(context(), **changes)


def test_portable_pipetting_contract_has_explicit_units_and_no_native_names():
    value = PipettingParameters.from_parameters({'aspiration_height_mm': 2.5, 'dispense_height_mm': 5,
        'aspiration_flow_rate_uL_s': 10})
    assert value.aspiration_flow_rate_uL_s == 10
    for parameters in ({'aspiration_height_mm': 1},
        {'aspiration_height_mm': 1, 'dispense_height_mm': 2, 'liquid_class': 'native'},
        {'aspiration_height_mm': -1, 'dispense_height_mm': 2},
        {'aspiration_height_mm': 1, 'dispense_height_mm': True},
        {'aspiration_height_mm': 1, 'dispense_height_mm': 2, 'aspiration_flow_rate_uL_s': 0}):
        with pytest.raises(ModuleProfileError): PipettingParameters.from_parameters(parameters)
