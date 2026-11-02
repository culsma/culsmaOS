"""Authorized static profile use cases shared by HTTP and MCP.

Selections here do not bind runs, apply configurations or commission hardware.
"""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import json
import re
from culsma_os.auth.interactors import AuthorizedInteractor
from .models import ModuleProfileDraft, ProfileReference, ModuleProfileError
from .profile_api_models import InstrumentProfileRequest
from .interactors import SaveModuleProfileInteractor
from .values import freeze_value, plain_value
from .repository import ModuleProfileRepository
from .ports import InstrumentMethodProviderPort
from .applicability import ProfileApplicabilityInteractor


class InstrumentProfileInteractor(AuthorizedInteractor):
    required_capability = 'configuration:drafts'

    def __init__(self, tokens, configurations, methods: InstrumentMethodProviderPort, profiles: ModuleProfileRepository):
        super().__init__(tokens)
        self.configurations, self.methods, self.profiles = configurations, methods, profiles

    def validate_request(self, request):
        if not isinstance(request, InstrumentProfileRequest):
            raise ModuleProfileError('PROFILE_REQUEST_INVALID')
        if request.action not in {'catalogue', 'list', 'read', 'validate', 'save'}:
            raise ModuleProfileError('PROFILE_ACTION_UNSUPPORTED')
        for key in ('device_id', 'module_id', 'profile_id', 'profile_revision', 'expected_revision', 'method_id', 'definition_revision'):
            value = getattr(request, key)
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 256):
                raise ModuleProfileError('PROFILE_IDENTITY_INVALID')
        required = ['device_id']
        if request.action != 'catalogue': required.append('module_id')
        if request.action == 'read': required += ['profile_id', 'profile_revision']
        if request.action in {'validate', 'save'}:
            required += ['profile_id', 'method_id', 'definition_revision', 'display_name']
            if (not isinstance(request.display_name, str) or not request.display_name.strip()
                    or len(request.display_name) > 120 or not isinstance(request.parameters, Mapping)):
                raise ModuleProfileError('PROFILE_DRAFT_INVALID')
            try:
                encoded = json.dumps(plain_value(freeze_value(request.parameters)), allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                raise ModuleProfileError('PROFILE_PARAMETERS_INVALID') from None
            if len(encoded.encode()) > 65536:
                raise ModuleProfileError('PROFILE_PARAMETERS_TOO_LARGE')
        if any(getattr(request, key) is None for key in required):
            raise ModuleProfileError('PROFILE_IDENTITY_REQUIRED')
        if request.action in {'catalogue', 'validate', 'save'}:
            if (not isinstance(request.draft_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request.draft_id) is None
                    or type(request.configuration_revision) is not int or request.configuration_revision < 1):
                raise ModuleProfileError('PROFILE_CONFIGURATION_REQUIRED')

    def encode(self, value):
        if is_dataclass(value):
            return {field.name: self.encode(getattr(value, field.name)) for field in fields(value)}
        if isinstance(value, Mapping): return {key: self.encode(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)): return [self.encode(item) for item in value]
        return value

    def perform(self, request):
        self.validate_request(request)
        base = {'scope': 'static_configuration', 'hardware_observed': False,
                'activation': 'not_applied', 'run_binding': 'not_bound'}
        if request.action == 'list':
            return {**base, 'profiles': self.encode(self.profiles.list_profiles(request.device_id, request.module_id))}
        if request.action == 'read':
            reference = ProfileReference(request.device_id, request.module_id, request.profile_id, request.profile_revision)
            return {**base, 'profile': self.encode(self.profiles.get_revision(reference))}
        configuration = self.configurations.read_for_instrument_profiles(request.draft_id, request.configuration_revision)
        methods = self.methods.for_configuration(configuration['driver'], configuration['configuration'], configuration['fingerprint'])
        modules = methods.list_instrument_modules(request.device_id)
        if request.module_id is not None:
            modules = tuple(module for module in modules if module.module_id == request.module_id)
            if len(modules) != 1: raise ModuleProfileError('PROFILE_MODULE_UNAVAILABLE')
        base['configuration'] = {key: configuration[key] for key in ('draft_id', 'revision', 'driver', 'fingerprint')}
        if request.action == 'catalogue':
            definitions = tuple(method for module in modules for method in methods.list_method_definitions(module))
            return {**base, 'modules': self.encode(modules), 'methods': self.encode(definitions)}
        draft = ModuleProfileDraft(modules[0], request.profile_id, request.expected_revision,
            request.method_id, request.definition_revision, request.display_name.strip(), request.parameters,
            ProfileApplicabilityInteractor().parse(request.applicability))
        service = SaveModuleProfileInteractor(self.tokens, methods, self.profiles)
        if request.action == 'validate':
            try:
                service.validate_draft(draft)
            except ModuleProfileError as error:
                return {**base, 'valid': False, 'code': error.code, 'diagnostics': list(error.diagnostics)}
            return {**base, 'valid': True, 'diagnostics': [], 'validation_basis': 'driver_static_rules'}
        service.validate_draft(draft)
        saved = self.profiles.save_revision(draft)
        return {**base, 'profile': self.encode(saved), 'validation_basis': 'driver_static_rules'}
