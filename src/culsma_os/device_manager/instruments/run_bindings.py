"""Freeze per-run selections and attach typed methods to projected operations."""
from dataclasses import replace
from .models import ProfileReference, MethodResolutionRequest, ModuleProfileError
from .selection import ProfileSelectionInteractor


class RunProfileBindingInteractor:
    def __init__(self, profiles, bindings, device=None):
        self.profiles, self.bindings, self.device = profiles, bindings, device

    def bind_run(self, run_id, selections):
        if selections is None: return
        if not isinstance(selections, dict) or not selections or len(selections) > 256:
            raise ModuleProfileError('PROFILE_RUN_BINDINGS_INVALID')
        saved = {}
        for step, value in selections.items():
            if not isinstance(step, str) or not step or not isinstance(value, dict) or set(value) != {'device_id','module_id','profile_id','revision'} or any(not isinstance(v, str) or not v for v in value.values()):
                raise ModuleProfileError('PROFILE_RUN_BINDINGS_INVALID')
            profile = self.profiles.get_revision(ProfileReference(**value))
            if profile.applicability is None:
                raise ModuleProfileError('PROFILE_APPLICABILITY_REQUIRED')
            saved[step] = profile
        self.bindings.save(run_id, saved)

    def require_unprofiled(self, run_id):
        if self.bindings.get(run_id):
            raise ModuleProfileError('PROFILE_EXECUTION_MODE_UNSUPPORTED')

    def prepare_batch(self, context, operations):
        profiles = self.bindings.get(context.run_id)
        if not profiles: return operations
        if set(profiles) - {op.intent.step_id for op in operations}:
            raise ModuleProfileError('PROFILE_STEP_NOT_PROJECTED')
        if not callable(getattr(self.device, 'profile_operation_context', None)):
            raise ModuleProfileError('PROFILE_OPERATION_CONTEXT_UNSUPPORTED')
        if not callable(getattr(self.device, 'instrument_profile_methods', None)):
            raise ModuleProfileError('INSTRUMENT_PROFILES_UNSUPPORTED')
        methods = self.device.instrument_profile_methods(context.layout_revision)
        result = []
        for op in operations:
            profile = profiles.get(op.intent.step_id)
            if profile is None:
                result.append(op)
                continue
            facts = self.device.profile_operation_context(context.run_id, op.intent, op.bindings)
            request = MethodResolutionRequest(context.run_id, op.intent.step_id, profile.reference, (),
                methods.configuration_revision, context.layout_revision, facts)
            # Use the captured immutable revision; the live profile store is not consulted.
            selection = ProfileSelectionInteractor(None, methods)
            selection.validate_profile_matches_module(request, profile, profile.module.kind)
            from .applicability import ProfileApplicabilityInteractor
            ProfileApplicabilityInteractor().require_matching_operation(profile.applicability, facts, context.run_id, op.intent.step_id)
            method = methods.validate_and_select_step_method(request, profile, ())
            selection.verify_selection_matches_request(request, profile, (), method)
            result.append(replace(op, method=method))
        return tuple(result)
