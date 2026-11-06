"""Prepare the shaker instrument independently through the driver contract."""
from ..execution import InstrumentExecutionPreparationInteractor
from ..interactors import ModuleProfileResolutionInteractor
from ..models import MethodResolutionRequest, ResolvedModuleMethod, ModuleProfileError


class ShakerProfileInteractor(ModuleProfileResolutionInteractor):
    def prepare_step_method(self, request: MethodResolutionRequest) -> ResolvedModuleMethod:
        if request.related_profiles:
            raise ModuleProfileError('SHAKER_RELATED_PROFILE_UNSUPPORTED')
        profile = self.selection.load_and_validate_profile_revision(request, 'shaker')
        result = self.methods.validate_and_select_step_method(request, profile, ())
        return self.selection.verify_selection_matches_request(request, profile, (), result)


class ShakerExecutionPreparationInteractor(InstrumentExecutionPreparationInteractor):
    capability = 'orbital_shake'

    def validate_intent(self, intent, capability):
        super().validate_intent(intent, capability)
        if intent.requires_motion_default and capability.get("default_motion") != "orbital":
            raise ValueError("PROCESSING_AGITATION_MOTION_DEFAULT_REQUIRED")
        from math import isfinite
        limits = capability.get('rate_range_rpm', [200, 3000])
        if (not isinstance(limits, (tuple, list)) or len(limits) != 2
                or any(type(v) not in (int, float) or not isfinite(v) for v in limits)
                or limits[0] > limits[1]):
            raise ValueError('PROCESSING_AGITATION_CAPABILITY_INVALID')
        if (type(intent.rate_rpm) is not int or not limits[0] <= intent.rate_rpm <= limits[1]):
            raise ValueError('PROCESSING_AGITATION_RATE_UNSUPPORTED')
