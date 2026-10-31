"""MCP settings adapter: typed request mapping to the existing UI use cases."""
from typing import Any, Literal
from culsma_os.workspace_manager.models import StationConfigurationRequest, ProgramBindingRequest, LabwareRequest
from culsma_os.lifecycle_manager.models import ConsoleActivationRequest, StationSelectionRequest
from culsma_os.developer_tools.models import FaultTestRequest


class MCPSettingsTools:
    def settings_tools(self):
        groups = [
            (self.station_selection, [(self.station_selection_status, True), (self.select_station_for_next_start, False)]),
            (self.configuration, [(self.configuration_profiles, True), (self.list_configurations, True),
                (self.read_configuration, True), (self.create_configuration, False),
                (self.save_configuration, False), (self.validate_configuration, True),
                (self.export_configuration, True), (self.export_vendor_layout, True),
                (self.import_vendor_layout, True)]),
            (self.bindings, [(self.review_program_bindings, True)]),
            (self.activation, [(self.configuration_status, True), (self.apply_configuration, False)]),
            (self.labware, [(self.labware_catalogue, True), (self.prepare_labware_change, False)]),
            (self.developer_tests, [(self.test_device_fault, False)]),
        ]
        return [(method, readonly) for owner, methods in groups if owner is not None for method, readonly in methods]

    def configuration_profiles(self) -> dict[str, Any]:
        """Read installed driver capabilities, layout models, choices and default templates."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('profiles'))

    def list_configurations(self) -> dict[str, Any]:
        """Read saved station configurations from the same store used by System Settings."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('list'))

    def read_configuration(self, draft_id: str, revision: int | None = None) -> dict[str, Any]:
        """Read a saved configuration, optionally at an exact immutable revision."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('get', draft_id, revision))

    def create_configuration(self, title: str, driver: str, configuration: dict[str, Any]) -> dict[str, Any]:
        """Save a new proposed configuration. This does not apply it or move equipment."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('create', title=title, driver=driver, configuration=configuration))

    def save_configuration(self, draft_id: str, expected_revision: int, title: str, driver: str, configuration: dict[str, Any]) -> dict[str, Any]:
        """Save configuration edits against the revision read earlier; stale edits are rejected."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('save', draft_id, expected_revision, title, driver, configuration))

    def validate_configuration(self, draft_id: str, revision: int) -> dict[str, Any]:
        """Run the same static driver checks as System Settings; not physical inspection."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('validate', draft_id, revision))

    def export_configuration(self, draft_id: str, revision: int) -> dict[str, Any]:
        """Return validated configuration JSON for this exact saved revision."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('export', draft_id, revision))

    def export_vendor_layout(self, draft_id: str, revision: int) -> dict[str, Any]:
        """Return the driver-generated layout archive with content and hashes; never executes it."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('export_layout', draft_id, revision))

    def import_vendor_layout(self, driver: str, layout_source: dict[str, Any]) -> dict[str, Any]:
        """Convert a bounded vendor layout package to OS configuration using the driver; does not save or apply it."""
        return self.configuration.execute(self.raw_credential, StationConfigurationRequest('import_layout', driver=driver, layout_source=layout_source))

    def review_program_bindings(self, draft_id: str, revision: int, program_id: str, snapshot_id: str) -> dict[str, Any]:
        """Review saved configuration bindings against the exact inspected program snapshot."""
        return self.bindings.execute(self.raw_credential, ProgramBindingRequest(draft_id, revision, program_id, snapshot_id))

    def configuration_status(self, request_id: str | None = None) -> dict[str, Any]:
        """Read the active configuration or an existing apply receipt; never repeats application."""
        return self.activation.execute(self.raw_credential, ConsoleActivationRequest('status', request_id=request_id))

    def apply_configuration(self, draft_id: str, revision: int, expected_fingerprint: str, request_id: str) -> dict[str, Any]:
        """Explicitly apply an exact validated configuration to an idle station. Poll configuration_status(request_id); do not resend an unknown outcome under a new ID. This records declared layout, not physical rack replacement."""
        return self.activation.execute(self.raw_credential, ConsoleActivationRequest('apply', draft_id, revision, expected_fingerprint, request_id))

    def labware_catalogue(self, expected_fingerprint: str) -> dict[str, Any]:
        """Read editable rack/slot targets and compatible models from the current driver catalogue."""
        return self.labware.execute(self.raw_credential, LabwareRequest('catalogue', expected_fingerprint))

    def prepare_labware_change(self, expected_fingerprint: str, action: Literal['place','replace','remove','replace-carrier'], target: str, model: str | None = None, name: str | None = None) -> dict[str, Any]:
        """Propose placement/removal/model changes or rack replacement using catalogue IDs. Returns a saved draft and impact; apply_configuration is a separate explicit operation."""
        change = {'action': action, 'target': target, **{key: value for key, value in {'model': model, 'name': name}.items() if value is not None}}
        return self.labware.execute(self.raw_credential, LabwareRequest('prepare', expected_fingerprint, change))

    def test_device_fault(self, scenario: Literal['tip_unavailable','liquid_insufficient','interrupted']) -> dict[str, Any]:
        """Run the Developer panel's detached fault test and return the same operator guidance; never alters station inventory or resumes a run."""
        return self.developer_tests.execute(self.raw_credential, FaultTestRequest(scenario))

    def station_selection_status(self) -> dict[str, Any]:
        """Read installed product workstations, this connection's profile, next-start selection and actual resident readiness. Works before starting the App."""
        return self.station_selection.execute(self.raw_credential, StationSelectionRequest('status'))

    def select_station_for_next_start(self, profile_id: str, expected_selected_profile: str) -> dict[str, Any]:
        """Persist a workstation choice against the selection read earlier. Does not stop or switch the running station. Restart the App and reconnect MCP when indicated; station_status verifies the actual driver."""
        return self.station_selection.execute(self.raw_credential, StationSelectionRequest('select',profile_id,expected_selected_profile))
