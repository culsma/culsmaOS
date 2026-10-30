from .repository import DeviceRepository, DeviceInspectionRepository


class DeviceInteractor:

    def __init__(self, repository: DeviceRepository, readiness, configured_snapshot=None):
        self.repository = repository
        self.readiness = readiness
        self.configured_snapshot = configured_snapshot
        self.restored_consumption = None
        self.consumables = None

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

    def select_simulation_run(self, run_id):
        if getattr(self.readiness, 'simulation_scope', 'station') != 'run':
            return
        if self.configured_snapshot.mode != 'simulation':
            raise ValueError('SIMULATION_SCOPE_REQUIRES_SIMULATION')
        self.readiness.begin_simulation_run(run_id)
        if self.consumables is not None:
            self.consumables.simulation_run_id = run_id

    def restore_consumables(self, device_id, evidence):
        consumption = self.consumables.restore(self.readiness,device_id) if self.consumables else evidence.known_consumption(device_id)
        # A new load can have the same count as the previous restoration.
        # Restore the authoritative current-load cursor even when its count is unchanged.
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

    def export_layout(self, driver, configuration):
        profiles, _ = self.discovery.discover()
        profile = profiles.get(driver)
        if profile is None or profile.describe().get('layout_export_supported') is not True:
            return None
        artifact = profile.export_layout(configuration)
        self.validate_layout_archive(artifact, configuration)
        return artifact

    def validate_layout_archive(self, artifact, configuration):
        import base64
        import binascii
        import hashlib
        import json
        import re
        from ..driver_framework.models import LayoutExportError
        if (not isinstance(artifact, dict) or artifact.get('encoding') != 'base64'
                or artifact.get('media_type') != 'application/zip'
                or not isinstance(artifact.get('name'), str)
                or re.fullmatch(r'[A-Za-z0-9_-]+\.zip', artifact['name']) is None
                or not isinstance(artifact.get('content'), str) or len(artifact['content']) > 4000000):
            raise LayoutExportError('Invalid native layout archive descriptor')
        try:
            content = base64.b64decode(artifact['content'], validate=True)
        except (ValueError, binascii.Error) as error:
            raise LayoutExportError('Invalid layout archive encoding') from error
        fingerprint = hashlib.sha256(json.dumps(configuration,sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if (not content.startswith(b'PK\x03\x04')
                or hashlib.sha256(content).hexdigest() != artifact.get('sha256')
                or fingerprint != artifact.get('configuration_sha256')):
            raise LayoutExportError('Layout archive differs from the saved configuration')

    def import_layout(self, driver, source):
        import base64
        import binascii
        import hashlib
        import json
        from ..driver_framework.models import LayoutImportError
        if (not isinstance(source, dict) or set(source) != {'name','encoding','content'}
                or source['encoding'] != 'base64' or not isinstance(source['name'],str)
                or not 1 <= len(source['name']) <= 180 or '/' in source['name'] or '\\' in source['name']
                or not isinstance(source['content'],str) or len(source['content']) > 1400000):
            raise LayoutImportError('Invalid bounded layout source')
        try:
            content = base64.b64decode(source['content'],validate=True)
        except (ValueError,binascii.Error) as error:
            raise LayoutImportError('Invalid layout source encoding') from error
        if not 1 <= len(content) <= 1024*1024:
            raise LayoutImportError('Layout source size is outside the import limit')
        profiles, _ = self.discovery.discover()
        profile = profiles.get(driver)
        if profile is None or profile.describe().get('layout_import_supported') is not True:
            return None
        result = profile.import_layout(content,source['name'])
        self.validate_layout_import(result,source['name'],hashlib.sha256(content).hexdigest())
        if result['complete'] and not profile.validate(result['configuration']).get('valid'):
            raise LayoutImportError('Imported configuration is not valid for its owning profile')
        return json.loads(json.dumps(result,allow_nan=False))

    def validate_layout_import(self, result, name, fingerprint):
        import json
        from ..driver_framework.models import LayoutImportError
        if (not isinstance(result,dict) or result.get('schema') != 'culsma_layout_import_v1'
                or result.get('source') != {'name':name,'sha256':fingerprint}
                or type(result.get('complete')) is not bool or not isinstance(result.get('candidate_configuration'),dict)
                or not isinstance(result.get('objects'),list) or not 1 <= len(result['objects']) <= 4096
                or not isinstance(result.get('diagnostics'),list) or len(result['diagnostics']) > 8192
                or result.get('activation') != 'not_applied' or result.get('physical_observation') is not False):
            raise LayoutImportError('Invalid configuration import report')
        if (result['complete'] and (result.get('configuration') != result['candidate_configuration'] or result['diagnostics'])
                or not result['complete'] and result.get('configuration') is not None):
            raise LayoutImportError('Incomplete conversion cannot supply an accepted configuration')
        try:
            encoded = json.dumps(result,allow_nan=False)
            if len(encoded.encode()) > 2000000:
                raise ValueError()
            from math import isfinite
            for row in result['objects']:
                if (not isinstance(row,dict) or any(not isinstance(row.get(k),str) for k in ('id','model','category','parent','site'))
                        or type(row.get('mapped')) is not bool or not isinstance(row.get('origin_mm'),list)
                        or len(row['origin_mm']) != 3 or any(type(v) not in (int,float) or not isfinite(v) for v in row['origin_mm'])
                        or type(row.get('angle_deg')) not in (int,float) or not isfinite(row['angle_deg'])):
                    raise ValueError()
            names = [row['id'] for row in result['objects']]
            if len(set(names)) != len(names) or any(not isinstance(name,str) or not name for name in names):
                raise ValueError()
            for row in result['diagnostics']:
                if not isinstance(row.get('code'),str) or not isinstance(row.get('message'),str):
                    raise ValueError()
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError) as error:
            raise LayoutImportError('Malformed configuration import data') from error

    def program_bindings(self, driver, configuration):
        profiles, _ = self.discovery.discover()
        profile = profiles.get(driver)
        project = getattr(profile,'program_bindings',None)
        return project(configuration) if callable(project) else None


from dataclasses import asdict
import json
import re
from .models import DeviceProfileRequest, DeviceProfileQueryPort, DeviceProfileQueryError


class ResidentDeviceProfileInteractor:
    def __init__(self, profiles: DeviceProfileQueryPort):self.profiles=profiles

    def execute(self, value):
        if not isinstance(value,dict) or set(value)-{'action','driver','configuration','layout_source'}:
            raise ValueError('DEVICE_PROFILE_REQUEST_INVALID')
        try:request=DeviceProfileRequest(**value)
        except TypeError as error:raise ValueError('DEVICE_PROFILE_REQUEST_INVALID') from error
        if not isinstance(request.action,str) or request.action not in {'describe','validate','export_layout','import_layout','program_bindings'}:
            raise ValueError('DEVICE_PROFILE_REQUEST_INVALID')
        if request.action=='describe':
            if any(v is not None for v in (request.driver,request.configuration,request.layout_source)):
                raise ValueError('DEVICE_PROFILE_REQUEST_INVALID')
            return self.validate_response('describe',self.profiles.describe())
        if not isinstance(request.driver,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request.driver) is None:
            raise ValueError('DEVICE_PROFILE_REQUEST_INVALID')
        importing=request.action=='import_layout'
        if (importing and (not isinstance(request.layout_source,dict) or request.configuration is not None)
                or not importing and (not isinstance(request.configuration,dict) or request.layout_source is not None)):
            raise ValueError('DEVICE_PROFILE_REQUEST_INVALID')
        try:
            if len(json.dumps(value,allow_nan=False).encode())>2*1024*1024:raise ValueError('too large')
        except (TypeError,ValueError,RecursionError) as error:raise ValueError('DEVICE_PROFILE_REQUEST_INVALID') from error
        try:
            result = self.profiles.import_layout(request.driver,request.layout_source) if importing else getattr(self.profiles,request.action)(request.driver,request.configuration)
            return self.validate_response(request.action,result)
        except ValueError as error:
            # Known driver diagnostics are codes, not native exception text or paths.
            code=getattr(error,'code','DEVICE_PROFILE_QUERY_REJECTED')
            raise ValueError(code if isinstance(code,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}',code) else 'DEVICE_PROFILE_QUERY_REJECTED') from error


    def validate_response(self,action,result):
        if result is None and action not in {'describe','validate'}:return None
        if not isinstance(result,dict):raise ValueError('DEVICE_PROFILE_RESPONSE_INVALID')
        try:
            if len(json.dumps(result,allow_nan=False).encode())>4*1024*1024-2048:
                raise ValueError('DEVICE_PROFILE_RESPONSE_TOO_LARGE')
        except (TypeError,ValueError,RecursionError) as error:
            raise ValueError('DEVICE_PROFILE_RESPONSE_INVALID') from error
        return result


class RemoteDeviceProfileInteractor:
    def __init__(self,resident):self.resident=resident

    def query(self,request: DeviceProfileRequest):
        try:return self.resident.execute({'action':'configuration-profile','profile_request':asdict(request)})
        except OSError as error:raise DeviceProfileQueryError('CONFIGURATION_PROFILE_HOST_UNAVAILABLE','unavailable') from error
        except ValueError as error:
            code=str(error)
            raise DeviceProfileQueryError(code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}',code) else 'CONFIGURATION_PROFILE_QUERY_REJECTED','conflict') from error

    def describe(self):return self.query(DeviceProfileRequest('describe'))
    def validate(self,driver,configuration):return self.query(DeviceProfileRequest('validate',driver,configuration))
    def export_layout(self,driver,configuration):return self.query(DeviceProfileRequest('export_layout',driver,configuration))
    def import_layout(self,driver,source):return self.query(DeviceProfileRequest('import_layout',driver,layout_source=source))
    def program_bindings(self,driver,configuration):return self.query(DeviceProfileRequest('program_bindings',driver,configuration))


class StationCapabilitiesInteractor:
    """Configured driver ports, never permissions or physical device discovery."""
    def __init__(self, driver, *, layout=False, loading_plan=False, labware_editor=False,
                 simulated_tip_replacement=False, fault_test=False):
        self.driver = driver
        self.support = dict(layout=layout, loading_plan=loading_plan, labware_editor=labware_editor,
                            simulated_tip_replacement=simulated_tip_replacement, fault_test=fault_test)

    def describe(self):
        reasons = {
            'layout': 'The selected driver has no layout reader.',
            'loading_plan': 'This driver uses preconfigured program bindings rather than a separate loading plan.',
            'labware_editor': 'The selected driver has no quick labware editor. Saved configuration editing is separate.',
            'simulated_tip_replacement': 'This session has no stock-replacement port. Normal simulation does not require manual replenishment.',
            'fault_test': 'The selected driver has no detached diagnostic-test port.'}
        return {'schema':'culsma_station_capabilities_v1','driver':self.driver,
                'source':'configured_driver_ports','physical_observation':False,
                'features':{key:{'supported':bool(value),'reason':None if value else reasons[key]}
                            for key,value in self.support.items()}}
