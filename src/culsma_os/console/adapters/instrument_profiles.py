"""Transport-only mapping for static instrument profiles."""
from dataclasses import fields
from typing import Any
from culsma_os.device_manager.instruments.profile_api_models import InstrumentProfileRequest
from culsma_os.device_manager.instruments.models import ModuleProfileError


class InstrumentProfileRequestMapper:
    def parse(self, payload):
        allowed = {field.name for field in fields(InstrumentProfileRequest)}
        if (not isinstance(payload, dict) or set(payload) - allowed
                or not {'action', 'device_id'} <= payload.keys()
                or any(value is not None and not isinstance(value, str)
                       for key, value in payload.items() if key not in {'configuration_revision', 'parameters', 'applicability'})
                or payload.get('configuration_revision') is not None and type(payload['configuration_revision']) is not int
                or payload.get('applicability') is not None and not isinstance(payload['applicability'], dict)
                or payload.get('parameters') is not None and not isinstance(payload['parameters'], dict)):
            raise ModuleProfileError('PROFILE_REQUEST_INVALID')
        return InstrumentProfileRequest(**payload)


class MCPInstrumentProfileTools:
    def instrument_profile_catalogue(self, draft_id: str, configuration_revision: int, device_id: str,
                                     module_id: str | None = None) -> dict[str, Any]:
        """Read driver-defined instrument methods and parameter schemas for an exact saved station configuration. Offline only; does not inspect hardware or bind a run."""
        return self.instrument_profiles.execute(self.raw_credential, InstrumentProfileRequest(
            'catalogue', device_id, module_id, draft_id, configuration_revision))

    def list_instrument_profiles(self, device_id: str, module_id: str) -> dict[str, Any]:
        """List all immutable saved revisions, including historical ones. Listing does not establish current compatibility."""
        return self.instrument_profiles.execute(self.raw_credential, InstrumentProfileRequest('list', device_id, module_id))

    def read_instrument_profile(self, device_id: str, module_id: str, profile_id: str, profile_revision: str) -> dict[str, Any]:
        """Read one exact saved instrument Profile revision; never substitute latest."""
        return self.instrument_profiles.execute(self.raw_credential, InstrumentProfileRequest(
            'read', device_id, module_id, profile_id=profile_id, profile_revision=profile_revision))

    def validate_instrument_profile(self, draft_id: str, configuration_revision: int, device_id: str,
            module_id: str, profile_id: str, method_id: str, definition_revision: str,
            display_name: str, parameters: dict[str, Any], applicability: dict[str, Any] | None = None) -> dict[str, Any]:
        """Check a proposed instrument Profile against driver static rules without saving, applying, running simulation or claiming scientific validation."""
        return self.instrument_profiles.execute(self.raw_credential, InstrumentProfileRequest(
            'validate', device_id, module_id, draft_id, configuration_revision, profile_id=profile_id,
            method_id=method_id, definition_revision=definition_revision, display_name=display_name, parameters=parameters, applicability=applicability))

    def save_instrument_profile(self, draft_id: str, configuration_revision: int, device_id: str,
            module_id: str, profile_id: str, method_id: str, definition_revision: str,
            display_name: str, parameters: dict[str, Any], expected_revision: str | None = None,
            applicability: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate and append an instrument Profile revision. For updates provide the last revision read; null creates a new identity. Does not apply to a workstation or experiment. After an uncertain response, list revisions before retrying."""
        return self.instrument_profiles.execute(self.raw_credential, InstrumentProfileRequest(
            'save', device_id, module_id, draft_id, configuration_revision, profile_id=profile_id,
            expected_revision=expected_revision, method_id=method_id, definition_revision=definition_revision,
            display_name=display_name, parameters=parameters, applicability=applicability))
