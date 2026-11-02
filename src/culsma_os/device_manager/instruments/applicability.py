"""OS-owned applicability contracts and checks; no vendor parameter interpretation."""
from dataclasses import dataclass
from math import isfinite
from .models import ModuleProfileError


@dataclass(frozen=True)
class AspirationVolumeRange:
    minimum: float
    maximum: float

    def __post_init__(self):
        if any(type(v) not in (int, float) or not isfinite(v) or v <= 0
               for v in (self.minimum, self.maximum)) or self.minimum > self.maximum:
            raise ModuleProfileError('PROFILE_VOLUME_RANGE_INVALID')


@dataclass(frozen=True)
class ProfileApplicability:
    operation: str
    source_models: tuple[str, ...] = ()
    destination_models: tuple[str, ...] = ()
    tip_models: tuple[str, ...] = ()
    per_aspiration_volume_uL: AspirationVolumeRange | None = None
    required_source_conditions: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.operation, str) or self.operation not in {'transfer', 'magnetic_flowthrough_transfer', 'magnetic_separation'}:
            raise ModuleProfileError('PROFILE_OPERATION_UNSUPPORTED')
        for name in ('source_models', 'destination_models', 'tip_models', 'required_source_conditions'):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(v, str) or not v.strip() for v in values) or len(set(values)) != len(values):
                raise ModuleProfileError('PROFILE_APPLICABILITY_INVALID')
        if set(self.required_source_conditions) - {'magnetically_held'}:
            raise ModuleProfileError('PROFILE_CONDITION_UNSUPPORTED')
        if self.per_aspiration_volume_uL is not None and not isinstance(self.per_aspiration_volume_uL, AspirationVolumeRange):
            raise ModuleProfileError('PROFILE_VOLUME_RANGE_INVALID')
        if self.operation == 'magnetic_flowthrough_transfer' and 'magnetically_held' not in self.required_source_conditions:
            raise ModuleProfileError('PROFILE_MAGNETIC_CONDITION_REQUIRED')
        if self.operation == 'magnetic_separation' and (self.destination_models or self.tip_models or self.per_aspiration_volume_uL or self.required_source_conditions):
            raise ModuleProfileError('PROFILE_MAGNET_APPLICABILITY_INVALID')


@dataclass(frozen=True)
class ProfileOperationContext:
    """Internal preparation facts, supplied by the execution owner, never MCP claims.

    Volumes describe every planned aspiration stroke after splitting. Conditions
    must come from the typed intent and condition ownership, not profile labels.
    """
    run_id: str
    step_id: str
    operation: str
    source_models: tuple[str, ...]
    destination_models: tuple[str, ...] = ()
    tip_models: tuple[str, ...] = ()
    aspiration_volumes_uL: tuple[float, ...] = ()
    source_conditions: tuple[str, ...] = ()

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in (self.run_id, self.step_id)):
            raise ModuleProfileError('PROFILE_EXECUTION_CONTEXT_REQUIRED')
        ProfileApplicability(self.operation, self.source_models, self.destination_models, self.tip_models,
            required_source_conditions=self.source_conditions)
        if not isinstance(self.aspiration_volumes_uL, tuple) or any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in self.aspiration_volumes_uL):
            raise ModuleProfileError('PROFILE_ASPIRATION_VOLUMES_INVALID')
        if not self.source_models or (self.operation != 'magnetic_separation' and
                (not self.destination_models or not self.tip_models or not self.aspiration_volumes_uL)):
            raise ModuleProfileError('PROFILE_OPERATION_FACTS_REQUIRED')
        if self.operation == 'magnetic_separation' and self.aspiration_volumes_uL:
            raise ModuleProfileError('PROFILE_MAGNET_APPLICABILITY_INVALID')


class ProfileApplicabilityInteractor:
    def parse(self, value):
        """Decode the shared JSON contract; reject unknown fields explicitly."""
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) - set(ProfileApplicability.__dataclass_fields__) or 'operation' not in value:
            raise ModuleProfileError('PROFILE_APPLICABILITY_INVALID')
        data = dict(value)
        for name in ('source_models', 'destination_models', 'tip_models', 'required_source_conditions'):
            if name in data:
                if not isinstance(data[name], (list, tuple)):
                    raise ModuleProfileError('PROFILE_APPLICABILITY_INVALID')
                data[name] = tuple(data[name])
        volume = data.get('per_aspiration_volume_uL')
        if volume is not None:
            if not isinstance(volume, dict) or set(volume) != {'minimum', 'maximum'}:
                raise ModuleProfileError('PROFILE_VOLUME_RANGE_INVALID')
            data['per_aspiration_volume_uL'] = AspirationVolumeRange(**volume)
        return ProfileApplicability(**data)

    def encode(self, applicability):
        from dataclasses import asdict
        if applicability is None:
            return None
        if not isinstance(applicability, ProfileApplicability):
            raise ModuleProfileError('PROFILE_APPLICABILITY_INVALID')
        return asdict(applicability)

    def require_matching_operation(self, applicability, context, run_id, step_id):
        if applicability is None:
            return
        if not isinstance(context, ProfileOperationContext):
            raise ModuleProfileError('PROFILE_OPERATION_CONTEXT_REQUIRED')
        if (context.run_id, context.step_id) != (run_id, step_id):
            raise ModuleProfileError('PROFILE_OPERATION_CONTEXT_MISMATCH')
        if applicability.operation != context.operation:
            raise ModuleProfileError('PROFILE_OPERATION_MISMATCH')
        for name in ('source_models', 'destination_models', 'tip_models'):
            allowed = getattr(applicability, name)
            actual = getattr(context, name)
            if allowed and (not actual or not set(actual) <= set(allowed)):
                raise ModuleProfileError('PROFILE_' + name.upper() + '_MISMATCH')
        if not set(applicability.required_source_conditions) <= set(context.source_conditions):
            raise ModuleProfileError('PROFILE_SOURCE_CONDITION_MISMATCH')
        volume = applicability.per_aspiration_volume_uL
        if volume and (not context.aspiration_volumes_uL or any(not volume.minimum <= v <= volume.maximum for v in context.aspiration_volumes_uL)):
            raise ModuleProfileError('PROFILE_ASPIRATION_VOLUME_MISMATCH')
