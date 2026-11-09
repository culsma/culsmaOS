"""Prepare the centrifuge instrument independently through the driver contract."""
from ..execution import InstrumentExecutionPreparationInteractor
from ..interactors import ModuleProfileResolutionInteractor
from ..models import MethodResolutionRequest, ResolvedModuleMethod, ModuleProfileError


class CentrifugeProfileInteractor(ModuleProfileResolutionInteractor):
    def prepare_step_method(self, request: MethodResolutionRequest) -> ResolvedModuleMethod:
        if request.related_profiles:
            raise ModuleProfileError('CENTRIFUGE_RELATED_PROFILE_UNSUPPORTED')
        profile = self.selection.load_and_validate_profile_revision(request, 'centrifuge')
        result = self.methods.validate_and_select_step_method(request, profile, ())
        return self.selection.verify_selection_matches_request(request, profile, (), result)


class CentrifugeExecutionPreparationInteractor(InstrumentExecutionPreparationInteractor):
    capability = 'centrifuge'

    def validate_intent(self, intent, capability):
        from math import isfinite
        super().validate_intent(intent, capability)
        if 'drive_ranges' not in capability:
            return
        ranges = capability['drive_ranges']
        limits = ranges.get(intent.drive_unit) if isinstance(ranges, dict) else None
        if limits is None:
            raise ValueError(f'PROCESSING_CENTRIFUGE_DRIVE_UNSUPPORTED: The configured module does not accept {intent.drive_unit}.')
        if (not isinstance(limits, (list, tuple)) or len(limits) != 2
                or any(type(value) not in (int, float) or not isfinite(value) for value in limits)
                or not 0 < limits[0] <= limits[1]):
            raise ValueError('PROCESSING_CENTRIFUGE_DRIVE_CAPABILITY_INVALID')
        if not limits[0] <= intent.drive_value <= limits[1]:
            raise ValueError(f'PROCESSING_CENTRIFUGE_DRIVE_UNSUPPORTED: Requested {intent.drive_value:g} {intent.drive_unit}; '
                             f'the configured module accepts {limits[0]:g}–{limits[1]:g} {intent.drive_unit}.')


class CentrifugeMethodBindingInteractor:
    def bind(self, intent, capability):
        from math import isfinite
        from culsma_os.device_manager.instruments.execution_models import CentrifugeIntent, CentrifugeSeparationIntent, ProcessingMethodProfile
        if isinstance(intent, CentrifugeIntent):
            return intent  # agit already contains its explicit language duration.
        if not isinstance(intent, CentrifugeSeparationIntent):
            raise ValueError("PROCESSING_METHOD_INTENT_UNSUPPORTED")
        if intent.duration_seconds is not None:
            if (type(intent.duration_seconds) not in (int, float)
                    or not isfinite(intent.duration_seconds) or intent.duration_seconds <= 0):
                raise ValueError("PROCESSING_DURATION_INVALID")
            return CentrifugeIntent(intent.step_id, intent.targets, intent.drive_value, intent.drive_unit,
                                    intent.duration_seconds, None, intent.program_kind, intent.environment_conditions)
        profiles = capability.get("method_profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("PROCESSING_METHOD_PROFILE_INVALID")
        profile = profiles.get(intent.program_kind)
        if profile is None:
            raise ValueError("PROCESSING_METHOD_PROFILE_REQUIRED")
        if (not isinstance(profile, dict) or set(profile) != {"profile_id", "revision", "duration_seconds"}
                or any(not isinstance(profile.get(k), str) or not profile[k].strip()
                       for k in ("profile_id", "revision"))
                or type(profile["duration_seconds"]) not in {int, float}
                or not isfinite(profile["duration_seconds"]) or profile["duration_seconds"] <= 0):
            raise ValueError("PROCESSING_METHOD_PROFILE_INVALID")
        binding = ProcessingMethodProfile(profile["profile_id"], profile["revision"], float(profile["duration_seconds"]))
        return CentrifugeIntent(intent.step_id, intent.targets, intent.drive_value, intent.drive_unit,
                                binding.duration_seconds, binding, intent.program_kind)
