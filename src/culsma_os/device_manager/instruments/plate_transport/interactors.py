"""Prepare the plate_transport instrument independently through the driver contract."""
from ..interactors import ModuleProfileResolutionInteractor
from ..models import MethodResolutionRequest, ResolvedModuleMethod, ModuleProfileError


class PlateTransportProfileInteractor(ModuleProfileResolutionInteractor):
    def prepare_step_method(self, request: MethodResolutionRequest) -> ResolvedModuleMethod:
        if request.related_profiles:
            raise ModuleProfileError('PLATE_TRANSPORT_RELATED_PROFILE_UNSUPPORTED')
        profile = self.selection.load_and_validate_profile_revision(request, 'plate_transport')
        result = self.methods.validate_and_select_step_method(request, profile, ())
        return self.selection.verify_selection_matches_request(request, profile, (), result)


class PlateTransportExecutionPreparationInteractor:
    """Prepare a resolved move; Workspace and Scheduler own positions and ordering."""
    def __init__(self, gateway):
        self.gateway = gateway

    def prepare_execution(self, effect_id, intent, context):
        return self.gateway.prepare_motion(effect_id, intent, context)
