"""Profile data contracts. Construction is not device validation or execution approval."""
from dataclasses import dataclass
from typing import Mapping
from .values import freeze_value


@dataclass(frozen=True)
class InstrumentModule:
    device_id: str
    module_id: str
    kind: str
    driver_id: str
    configuration_revision: str
    shared_resource_ids: tuple[str, ...]


@dataclass(frozen=True)
class MethodDefinition:
    module: InstrumentModule
    method_id: str
    definition_revision: str
    display_name: str
    parameter_schema: Mapping[str, object]


    def __post_init__(self):
        object.__setattr__(self, "parameter_schema", freeze_value(self.parameter_schema))


@dataclass(frozen=True)
class ProfileReference:
    device_id: str
    module_id: str
    profile_id: str
    revision: str


@dataclass(frozen=True)
class ModuleProfileDraft:
    module: InstrumentModule
    profile_id: str
    expected_revision: str | None
    method_id: str
    definition_revision: str
    display_name: str
    parameters: Mapping[str, object]


    def __post_init__(self):
        object.__setattr__(self, "parameters", freeze_value(self.parameters))


@dataclass(frozen=True)
class ModuleProfileRevision:
    reference: ProfileReference
    module: InstrumentModule
    method_id: str
    definition_revision: str
    display_name: str
    parameters: Mapping[str, object]


    def __post_init__(self):
        object.__setattr__(self, "parameters", freeze_value(self.parameters))


@dataclass(frozen=True)
class ModuleCatalogueRequest:
    device_id: str
    module_id: str | None = None


@dataclass(frozen=True)
class ModuleCatalogue:
    modules: tuple[InstrumentModule, ...]
    methods: tuple[MethodDefinition, ...]
    profiles: tuple[ModuleProfileRevision, ...]


@dataclass(frozen=True)
class ProfileValidation:
    valid: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class MethodResolutionRequest:
    """A method selection for an existing step, not a second experiment language.

Related profiles support combinations such as magnet + pipetting. Referencing a
step does not replace its typed semantic intent or existing device preflight.
No physical coordinates or material state are duplicated here.
"""
    run_id: str
    step_id: str
    profile: ProfileReference
    related_profiles: tuple[ProfileReference, ...]
    configuration_revision: str
    layout_revision: str


@dataclass(frozen=True)
class ResolvedModuleMethod:
    """Exact configuration binding from the preparation-only service; never a device execution receipt.

The execution owner must persist this selection in its run preparation and pass
it alongside the original typed intent/bindings to driver preparation. Actual
intent compatibility, readiness, resource permits and execution evidence remain
mandatory. This result alone cannot authorize or start an action.
"""
    run_id: str
    step_id: str
    profile: ModuleProfileRevision
    related_profiles: tuple[ModuleProfileRevision, ...]
    configuration_revision: str
    layout_revision: str


class ModuleProfileError(ValueError):
    def __init__(self, code: str, diagnostics: tuple[str, ...] = ()):
        super().__init__(code)
        self.code = code
        self.diagnostics = diagnostics
