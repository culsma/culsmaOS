"""Prepare the magnetic instrument alone; program ordering belongs to the scheduler."""
from math import isfinite
from culsma_os.workspace_manager.models import ResolvedContainerRef
from .models import MagneticSeparationRequest, PreparedMagneticSeparation
from .ports import MagneticPreparationPort
from ..execution import InstrumentExecutionPreparationInteractor
from ..interactors import ModuleProfileResolutionInteractor
from ..models import MethodResolutionRequest, ResolvedModuleMethod, ModuleProfileError


class MagnetProfileInteractor(ModuleProfileResolutionInteractor):
    def prepare_step_method(self, request: MethodResolutionRequest) -> ResolvedModuleMethod:
        """Select a saved magnet method without requiring any pipetting operation."""
        if request.related_profiles:
            raise ModuleProfileError('MAGNET_RELATED_PROFILE_UNSUPPORTED')
        profile = self.selection.load_and_validate_profile_revision(request, 'magnet')
        result = self.methods.validate_and_select_step_method(request, profile, ())
        return self.selection.verify_selection_matches_request(request, profile, (), result)


class MagneticSeparationPreparationInteractor:
    """Internal device entry; inputs contain no language AST or material mutation."""
    def __init__(self, profiles: MagnetProfileInteractor, driver: MagneticPreparationPort):
        self.profiles = profiles
        self.driver = driver

    def validate_request(self, request: MagneticSeparationRequest) -> None:
        if not isinstance(request, MagneticSeparationRequest):
            raise ModuleProfileError('MAGNET_REQUEST_INVALID')
        context = request.method
        if (not context.run_id or not context.step_id or request.layout.run_id != context.run_id
                or request.layout.revision != context.layout_revision):
            raise ModuleProfileError('MAGNET_LAYOUT_CONTEXT_MISMATCH')
        if (type(request.duration_seconds) not in (int, float)
                or not isfinite(request.duration_seconds) or request.duration_seconds <= 0):
            raise ModuleProfileError('MAGNET_DURATION_INVALID')
        if (not request.targets or any(not isinstance(t, ResolvedContainerRef) for t in request.targets)
                or len(set(request.targets)) != len(request.targets)):
            raise ModuleProfileError('MAGNET_TARGETS_INVALID')
        bindings = request.layout.bindings
        if len({b.reference for b in bindings}) != len(bindings):
            raise ModuleProfileError('MAGNET_BINDINGS_AMBIGUOUS')
        if not set(request.targets) <= {b.reference for b in bindings}:
            raise ModuleProfileError('MAGNET_TARGET_UNBOUND')

    def prepare_magnetic_separation(self, request: MagneticSeparationRequest) -> PreparedMagneticSeparation:
        self.validate_request(request)
        method = self.profiles.prepare_step_method(request.method)
        details = self.driver.prepare_magnetic_separation(request, method)
        return PreparedMagneticSeparation(request, method, details)


class MagnetExecutionPreparationInteractor(InstrumentExecutionPreparationInteractor):
    """Runtime magnetic entry. Program ordering and material meaning stay with OS owners."""
    capability = 'magnetic_separation'

    def prepare_release(self, effect_id, intent, context, bindings=()):
        """Prepare only the condition release; Scheduler owns its journal and lifetime."""
        from ..execution_models import MagneticReleaseIntent
        if not isinstance(intent, MagneticReleaseIntent):
            raise ValueError('PROCESSING_MAGNETIC_RELEASE_INTENT_REQUIRED')
        return self.gateway.prepare_processing(effect_id, intent, context, bindings)
