"""Profile services: save and prepare_step_method are callable, not registered in the App.

Protected UI/MCP calls must use inherited execute(raw_credential, request).
Internal resolution is a peer-module service, never an alternative public entry.
No live App entry, current caller or execution engine is changed here.
"""
from abc import ABC, abstractmethod
from culsma_os.auth.interactors import AuthorizedInteractor
from .models import (
    ModuleCatalogueRequest, ModuleCatalogue, ModuleProfileDraft,
    ModuleProfileRevision, MethodResolutionRequest, ResolvedModuleMethod, ModuleProfileError,
)
from .ports import ModuleMethodPort
from .repository import ModuleProfileRepository
from .selection import ProfileSelectionInteractor


class ModuleCatalogueInteractor(AuthorizedInteractor, ABC):
    required_capability = 'configuration:drafts'

    def __init__(self, tokens, methods: ModuleMethodPort, profiles: ModuleProfileRepository):
        super().__init__(tokens)
        self.methods = methods
        self.profiles = profiles

    def perform(self, request: ModuleCatalogueRequest) -> ModuleCatalogue:
        if not isinstance(request, ModuleCatalogueRequest):
            raise ModuleProfileError('PROFILE_CATALOGUE_REQUEST_INVALID')
        modules = self.methods.list_instrument_modules(request.device_id)
        if request.module_id is not None:
            modules = tuple(m for m in modules if m.module_id == request.module_id)
            if not modules:
                raise ModuleProfileError('PROFILE_MODULE_UNAVAILABLE')
        definitions = tuple(d for m in modules for d in self.methods.list_method_definitions(m))
        profiles = tuple(p for m in modules for p in self.profiles.list_profiles(m.device_id, m.module_id))
        return ModuleCatalogue(modules, definitions, profiles)



class SaveModuleProfileInteractor(AuthorizedInteractor):
    required_capability = 'configuration:drafts'

    def __init__(self, tokens, methods: ModuleMethodPort, profiles: ModuleProfileRepository):
        super().__init__(tokens)
        self.methods = methods
        self.profiles = profiles

    def perform(self, request: ModuleProfileDraft) -> ModuleProfileRevision:
        current = [module for module in self.methods.list_instrument_modules(request.module.device_id)
                   if module.module_id == request.module.module_id]
        if len(current) != 1 or current[0] != request.module:
            raise ModuleProfileError('PROFILE_MODULE_STALE')
        definitions = [method for method in self.methods.list_method_definitions(request.module)
                       if method.method_id == request.method_id]
        if len(definitions) != 1 or definitions[0].definition_revision != request.definition_revision:
            raise ModuleProfileError('PROFILE_DEFINITION_STALE')
        validation = self.methods.validate_profile_parameters(request)
        if not validation.valid:
            raise ModuleProfileError('PROFILE_PARAMETERS_REJECTED', validation.diagnostics)
        return self.profiles.save_revision(request)


class ModuleProfileResolutionInteractor(ABC):
    def __init__(self, methods: ModuleMethodPort, selection: ProfileSelectionInteractor):
        self.methods = methods
        self.selection = selection

    @abstractmethod
    def prepare_step_method(self, request: MethodResolutionRequest) -> ResolvedModuleMethod:
        """Shared internal contract for execution-preparation owners.

        Load exact revisions using profiles.get_revision; delegate compatibility
        to methods.validate_and_select_step_method against current module/configuration/layout facts.
        Reject missing, stale or incompatible selections. Return a selection for
        the run owner to freeze; do not dispatch, acquire execution permits, alter
        semantic intents, or claim completion. Drivers still preflight the actual
        typed intent and bindings before any action.
        """
        raise NotImplementedError('Planned module method resolution')
