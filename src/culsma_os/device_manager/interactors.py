from .repository import DeviceRepository, DeviceInspectionRepository


class DeviceInteractor:

    def __init__(self, repository: DeviceRepository, readiness, configured_snapshot=None):
        self.repository = repository
        self.readiness = readiness
        self.configured_snapshot = configured_snapshot
        self.restored_consumption = None

    def register(self, snapshot):
        if snapshot.mode != "simulation":
            raise ValueError("OS_PHYSICAL_DEVICE_UNSUPPORTED")
        self.repository.put(snapshot)

    def get(self, device_id):
        try:
            return self.repository.get(device_id)
        except KeyError:
            if self.configured_snapshot is not None and self.configured_snapshot.device_id == device_id:
                return self.configured_snapshot
            raise

    def require_session_configuration(self):
        if self.configured_snapshot is not None:
            current = self.repository.get(self.configured_snapshot.device_id)
            if current != self.configured_snapshot:
                raise ValueError("DEVICE_SESSION_CONFIGURATION_MISMATCH")

    def admit_session(self, allow_reconfiguration=False):
        if self.configured_snapshot is None:
            return
        try:
            current = self.repository.get(self.configured_snapshot.device_id)
        except KeyError:
            self.register(self.configured_snapshot)
            return
        if current != self.configured_snapshot:
            if not allow_reconfiguration:
                raise ValueError("DEVICE_SESSION_CONFIGURATION_MISMATCH")
            self.register(self.configured_snapshot)
        else:
            self.register(self.configured_snapshot)  # Adopt an identical legacy catalog under run ownership.

    def validate_ready(self, context):
        current = self.get(context.device_id)
        if (
            current.mode,
            current.configuration_revision,
            current.calibration_revision,
        ) != (
            context.mode,
            context.configuration_revision,
            context.calibration_revision,
        ):
            raise ValueError("DEVICE_CONFIGURATION_STALE")
        self.readiness.check_ready()

    def restore_consumables(self, device_id, evidence):
        consumption = evidence.known_consumption(device_id)
        if consumption != self.restored_consumption:
            self.readiness.restore_consumables(consumption)
            self.restored_consumption = dict(consumption)


class DeviceInspectionInteractor:
    """Assemble owner observations; never load a session or advance execution."""
    def __init__(self, repository: DeviceInspectionRepository, snapshot, workspace, resources, evidence, station_path, station_snapshot):
        self.repository, self.snapshot = repository, snapshot
        self.workspace, self.resources, self.evidence = workspace, resources, evidence
        self.station_path, self.station_snapshot = station_path, station_snapshot

    def execute(self):
        from datetime import datetime, timezone
        with self.snapshot, self.station_snapshot:
            devices = self.repository.snapshots()
            resources = self.resources.inspect()
            reports = [self.describe(device, resources) for device in devices]
            return {'source': 'os_records', 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'consistency': 'one_read_snapshot_per_store', 'hardware_observed': False,
                    'run_store': str(self.snapshot.path.resolve()), 'station_store': str(self.station_path.resolve()),
                    'registration': 'recorded' if devices else 'not_recorded',
                    'devices': reports,
                    'resources': {key: value for key, value in resources.items() if key != 'station_usage'}}

    def describe(self, device, resources):
        from pathlib import Path
        evidence = self.evidence.inspect(device.device_id)
        positions = self.workspace.inspect(device, evidence)
        if any(Path(record['run_store']).resolve() != self.snapshot.path.resolve()
               for record in resources['station_reservations']):
            positions = {**positions, 'status': 'unknown', 'current': None,
                         'unresolved_motion': [*positions['unresolved_motion'], 'external_run_store_active']}
        elif positions['scope'] != 'station' and any(
                Path(store).resolve() != self.snapshot.path.resolve() for store in resources['station_run_stores']):
            positions = {**positions, 'status': 'unknown', 'current': None,
                         'unresolved_motion': [*positions['unresolved_motion'], 'external_run_store_history']}
        unresolved = [self.describe_operation(operation) for operation in evidence.operations
                      if operation.evidence is None or operation.evidence.outcome not in {'completed', 'rejected'}]
        return {'device_id': device.device_id, 'mode': device.mode,
                'configuration_revision': device.configuration_revision,
                'calibration_revision': device.calibration_revision,
                'positions': positions, 'evidence_accounting': evidence.accounting, 'unresolved_operations': unresolved,
                'consumables': self.resources.consumables(device, evidence, resources,
                    unresolved or positions['unresolved_motion'])}

    def describe_operation(self, operation):
        attempt, receipt = operation.attempt, operation.evidence
        return {'run_id': attempt.run_id, 'attempt_id': attempt.attempt_id, 'effect_id': attempt.effect_id,
                'step_id': attempt.context.get('step_id'),
                'operation_kind': attempt.context.get('description', {}).get('operation_kind', 'transfer'),
                'status': receipt.outcome if receipt else 'awaiting_evidence'}


class DeviceProfileInteractor:
    def __init__(self, discovery):
        self.discovery = discovery

    def describe(self):
        profiles, unavailable = self.discovery.discover()
        return {'profiles':[{'driver':name,**profile.describe()} for name,profile in profiles.items()],
                'unavailable':list(unavailable)}

    def validate(self, driver, configuration):
        profiles, unavailable = self.discovery.discover()
        if driver not in profiles:
            return {'valid':False,'diagnostics':[{'code':'PROFILE_UNAVAILABLE','path':'/driver',
                'message':'Install a driver with the offline configuration profile capability'}],
                'scope':'No device or program preflight performed'}
        return profiles[driver].validate(configuration)

    def program_bindings(self, driver, configuration):
        profiles, _ = self.discovery.discover()
        profile = profiles.get(driver)
        project = getattr(profile,'program_bindings',None)
        return project(configuration) if callable(project) else None
