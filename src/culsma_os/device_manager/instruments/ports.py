"""Driver capability for offline profile preparation; implementations belong to drivers.

Explicit composition injects this contract; automatic discovery remains pending. No vendor
imports or automatic fallbacks belong in Device Manager. Method definitions
must declare supported parameters, units, bounds and explicit defaults; unknown
fields or unsupported combinations must be rejected, never silently discarded.
"""
from typing import Protocol
from .models import (
    InstrumentModule, MethodDefinition, ModuleProfileDraft, ModuleProfileRevision,
    MethodResolutionRequest, ProfileValidation, ResolvedModuleMethod,
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
