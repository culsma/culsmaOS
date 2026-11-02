"""Driver capability for offline profile preparation; implementations belong to drivers.

Optional device factories expose build_instrument_methods for static management. No vendor
imports or automatic fallbacks belong in Device Manager. Method definitions
must declare supported parameters, units, bounds and explicit defaults; unknown
fields or unsupported combinations must be rejected, never silently discarded.
"""
from typing import Protocol
from .models import (
    InstrumentModule, MethodDefinition, ModuleProfileDraft, ModuleProfileRevision,
    MethodResolutionRequest, ProfileValidation, ResolvedModuleMethod, TranslatedInstrumentMethod,
)


class ModuleMethodPort(Protocol):
    def list_instrument_modules(self, device_id: str) -> tuple[InstrumentModule, ...]: ...

    def list_method_definitions(self, module: InstrumentModule) -> tuple[MethodDefinition, ...]: ...

    def validate_profile_parameters(self, draft: ModuleProfileDraft) -> ProfileValidation: ...

    def validate_and_select_step_method(
        self, request: MethodResolutionRequest,
        profile: ModuleProfileRevision,
        related_profiles: tuple[ModuleProfileRevision, ...],
    ) -> ResolvedModuleMethod: ...


class InstrumentMethodProviderPort(Protocol):
    def for_configuration(self, driver: str, configuration: dict, revision: str) -> ModuleMethodPort:
        """Return offline method rules for this exact configuration; never open hardware."""
        ...


class InstrumentMethodTranslationPort(Protocol):
    def translate_step_method(self, method: ResolvedModuleMethod) -> "TranslatedInstrumentMethod":
        """Convert a pinned OS selection into an isolated vendor payload; no dispatch."""
        ...
