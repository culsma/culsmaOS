"""Shared exact-version checks; owns no vendor parameter semantics."""
from .models import MethodResolutionRequest, ModuleProfileRevision, ModuleProfileError, ResolvedModuleMethod
from .ports import ModuleMethodPort
from .repository import ModuleProfileRepository


class ProfileSelectionInteractor:
    def __init__(self, profiles: ModuleProfileRepository, methods: ModuleMethodPort):
        self.profiles = profiles
        self.methods = methods

    def load_and_validate_profile_revision(self, request: MethodResolutionRequest, kind: str) -> ModuleProfileRevision:
        if not request.run_id or not request.step_id:
            raise ModuleProfileError('PROFILE_EXECUTION_CONTEXT_REQUIRED')
        references = (request.profile, *request.related_profiles)
        if len(set(references)) != len(references):
            raise ModuleProfileError('PROFILE_SELECTION_DUPLICATE')
        if any(ref.device_id != request.profile.device_id for ref in references):
            raise ModuleProfileError('PROFILE_DEVICE_MISMATCH')
        profile = self.profiles.get_revision(request.profile)
        self.validate_profile_matches_module(request, profile, kind)
        from .applicability import ProfileApplicabilityInteractor
        ProfileApplicabilityInteractor().require_matching_operation(profile.applicability, request.operation_context, request.run_id, request.step_id)
        return profile

    def validate_profile_matches_module(self, request, profile, kind):
        if profile.reference != request.profile:
            raise ModuleProfileError('PROFILE_REFERENCE_MISMATCH')
        module = profile.module
        if (module.device_id, module.module_id) != (request.profile.device_id, request.profile.module_id):
            raise ModuleProfileError('PROFILE_MODULE_MISMATCH')
        if module.kind != kind:
            raise ModuleProfileError('PROFILE_KIND_MISMATCH')
        if module.configuration_revision != request.configuration_revision:
            raise ModuleProfileError('PROFILE_CONFIGURATION_STALE')
        current = [m for m in self.methods.list_instrument_modules(module.device_id) if m.module_id == module.module_id]
        if len(current) != 1 or current[0] != module:
            raise ModuleProfileError('PROFILE_MODULE_STALE')
        definitions = [m for m in self.methods.list_method_definitions(module) if m.method_id == profile.method_id]
        if len(definitions) != 1 or definitions[0].definition_revision != profile.definition_revision:
            raise ModuleProfileError('PROFILE_DEFINITION_STALE')

    def verify_selection_matches_request(self, request, profile, related, result: ResolvedModuleMethod):
        expected = ResolvedModuleMethod(request.run_id, request.step_id, profile, related,
                                        request.configuration_revision, request.layout_revision, request.operation_context)
        if result != expected:
            raise ModuleProfileError('PROFILE_RESOLUTION_MISMATCH')
        return result
