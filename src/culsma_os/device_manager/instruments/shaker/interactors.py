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
        if not 200 <= intent.rate_rpm <= 3000 or int(intent.rate_rpm) != intent.rate_rpm:
            raise ValueError('PROCESSING_AGITATION_RATE_UNSUPPORTED')
