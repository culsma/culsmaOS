"""Check a proposed loading against the registered device before creating a run."""


from culsma_os.driver_framework.models import DeviceConfigurationReadPort


class SetupProgramPreflightInteractor:
    def __init__(self, devices, scopes, snapshot_reader: DeviceConfigurationReadPort | None = None, config_path=None):
        self.devices, self.scopes = devices, scopes
        self.snapshot_reader, self.config_path = snapshot_reader, config_path

    def inspect(self, compiled, catalogue, loading, workflow=None):
        try:
            configured = self.snapshot_reader.execute(self.config_path) if self.snapshot_reader is not None else None
            snapshot, positions = self.devices.preparation_snapshot(catalogue, configured)
            scope = self.scopes.build(snapshot, catalogue, loading, positions)
            try:
                report, _ = scope.preflight.inspect(compiled.plan, compiled.state, 'preview',
                    workflow=workflow if workflow and workflow.get('enabled') else None)
                report['issues'] = PreparationIssueInteractor().describe(report['diagnostics'])
                return report
            finally:
                scope.close()
        except ValueError as error:
            diagnostics = [{'code': str(error).split(':', 1)[0], 'message': str(error)}]
            return {'status': 'rejected', 'checked_effects': 0, 'diagnostics': diagnostics,
                    'issues': PreparationIssueInteractor().describe(diagnostics)}


class PreparationIssueInteractor:
    """Explain preparation blockers without claiming the equipment was inspected."""
    explanations = {
        'INSTRUMENT_DRIVER_UNAVAILABLE': ('No driver provides the requested instrument operation in this execution mode.', 'Select a workstation with a compatible driver.'),
        'INSTRUMENT_DEVICE_NOT_CONFIGURED': ('The driver supports this operation, but no corresponding device is configured.', 'Connect or configure the corresponding device.'),
        'INSTRUMENT_DEVICE_DISCONNECTED': ('The configured device is disconnected.', 'Check the device connection before running.'),
        'PROCESSING_LABWARE_UNSUPPORTED': ('The configured instruments cannot accept the assigned labware.', 'Check the sample container and instrument placement.'),
        'PROCESSING_MODULE_UNAVAILABLE': ('No configured device can perform this step.', 'Check the required environment or processing conditions and configure a compatible module.'),
        'PROCESSING_AGITATION_MOTION_UNSUPPORTED': ('This mixing motion is not supported by the current execution path.', 'Review the mixing step and select an implemented mixing method; do not substitute one without checking the protocol.'),
        'PROCESSING_MAGNETIC_PROGRAM_UNSUPPORTED': ('This magnetic separation program is not supported by the current execution path.', 'Review the magnetic program and the supported separation method.'),
        'PROCESSING_MAGNETIC_ENVIRONMENT_TARGETS': ('The magnetic condition cannot be mapped to these containers.', 'Check which containers must remain on the magnet and their configured positions.'),
        'PROCESSING_CENTRIFUGE_SEPARATION_SCOPE_UNSUPPORTED': ('This centrifuge separation cannot be mapped by the current execution path.', 'Review the separation targets and method before proceeding.'),
        'TRANSFER_CENTRIFUGE_SCOPE_UNSUPPORTED': ('This fraction transfer cannot be mapped to the centrifuge separation.', 'Review the separated fractions and their destination containers.'),
        'PROCESSING_MAGNETIC_ENVIRONMENT_UNSUPPORTED': ('This magnetic environment cannot be applied by the current execution path.', 'Review the field and the environment scope for this step.'),
        'TRANSFER_CONSTRAINT_UNSUPPORTED': ('The current pipetting path cannot honor a transfer requirement.', 'Review the transfer constraints and choose a compatible method or device.'),
        'TRANSFER_ENVIRONMENT_CONDITION_UNSUPPORTED': ('The current pipetting path cannot maintain the requested environment during transfer.', 'Choose a pipetting device or method that supports the requested temperature or atmosphere.'),
        'DRIVER_TRANSFER_SELECTION_UNSUPPORTED': ('The driver does not provide the requested separated-fraction transfer.', 'Choose a driver method that supports the requested fraction, including pellet recovery when needed.'),
    }

    def describe(self, diagnostics):
        result = []
        for diagnostic in diagnostics:
            message = diagnostic.get('message', '')
            code = message.split(':', 1)[0]
            explanation, action = self.explanations.get(code, (
                message if ': ' in message else 'A required execution condition could not be validated.',
                'Review the indicated protocol step and its workstation configuration.'))
            result.append({'code': code or diagnostic.get('code'), 'summary': explanation,
                           'action': action, 'node_id': diagnostic.get('node_id'),
                           'span': diagnostic.get('span'), 'detail': message})
        return result
