"""Prepare the incubator instrument independently through the driver contract."""
from ..execution import InstrumentExecutionPreparationInteractor
from ..interactors import ModuleProfileResolutionInteractor
from ..models import MethodResolutionRequest, ResolvedModuleMethod, ModuleProfileError


class IncubatorProfileInteractor(ModuleProfileResolutionInteractor):
    def prepare_step_method(self, request: MethodResolutionRequest) -> ResolvedModuleMethod:
        if request.related_profiles:
            raise ModuleProfileError('INCUBATOR_RELATED_PROFILE_UNSUPPORTED')
        profile = self.selection.load_and_validate_profile_revision(request, 'incubator')
        result = self.methods.validate_and_select_step_method(request, profile, ())
        return self.selection.verify_selection_matches_request(request, profile, (), result)


class IncubatorExecutionPreparationInteractor(InstrumentExecutionPreparationInteractor):
    capability = 'thermal_hold'

    def validate_intent(self, intent, capability):
        from math import isfinite
        super().validate_intent(intent, capability)
        limits = capability.get('temperature_range_celsius', [4, 95])
        if (not isinstance(limits, (tuple, list)) or len(limits) != 2
                or any(type(v) not in (int, float) or not isfinite(v) for v in limits)
                or limits[0] > limits[1]):
            raise ValueError('PROCESSING_TEMPERATURE_CAPABILITY_INVALID')
        if not limits[0] <= intent.temperature_celsius <= limits[1]:
            raise ValueError('PROCESSING_TEMPERATURE_UNSUPPORTED')
