"""Durable device-service admission; driver owns hardware semantics and evidence."""
import json
import re
from .service_ports import StationServicePort

class StationServiceRepository:
    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS os_station_services (request_id TEXT PRIMARY KEY, identity TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL)")

    def get(self, request_id):
        row = self.connection.execute('SELECT identity,state,result FROM os_station_services WHERE request_id=?',(request_id,)).fetchone()
        return None if row is None else (json.loads(row[0]),row[1],json.loads(row[2]))

    def unsettled(self):
        return self.connection.execute("SELECT request_id FROM os_station_services WHERE state NOT IN ('completed','rejected','cancelled') LIMIT 1").fetchone()

    def admit(self, request_id, identity):
        with self.connection:
            if self.unsettled(): raise ValueError('STATION_SERVICE_UNRESOLVED')
            self.connection.execute('INSERT INTO os_station_services VALUES(?,?,?,?)',
                (request_id,json.dumps(identity,sort_keys=True),'pending','{}'))

    def settle(self, request_id, value):
        previous = self.get(request_id)
        if previous and previous[0].get('operation') == 'native':
            value = {**value, 'execution_origin': 'native_debug', 'experiment_verified': False,
                     'debug_reason': previous[0].get('debug_reason')}
        state = value.get('state','unknown')
        if state not in ('accepted','running','completed','rejected','unknown','cancelled'): state='unknown'
        with self.connection:
            changed = self.connection.execute("UPDATE os_station_services SET state=?,result=? WHERE request_id=? AND state!='cancelled'",
                (state,json.dumps(value),request_id)).rowcount
            if not changed:
                previous = self.get(request_id)
                if previous and previous[1] == 'cancelled':
                    return {'request_id':request_id,**previous[2],'state':'cancelled'}
        return {'request_id':request_id,**value,'state':state}

class StationServiceInteractor:
    def __init__(self, repository, port: StationServicePort | None, configuration, physical_permission=None, run_evidence=None, *, native_debug_enabled=False):
        self.repository,self.port,self.configuration=repository,port,configuration
        self.physical_permission = physical_permission
        self.native_debug_enabled = native_debug_enabled
        self.run_evidence = run_evidence

    def require_settled(self):
        if self.repository.unsettled(): raise ValueError('STATION_SERVICE_UNRESOLVED')

    def close(self):
        close = getattr(self.port, 'close', None)
        if close is not None:
            close()

    def execute(self, request, require_idle):
        if not isinstance(request,dict) or set(request)-{'action','request_id','method_id','bundle_sha256','acknowledge_clearance','enabled','entrypoint','files','mode','offset','limit','stream','run_id','attempt_id','debug_reason'}:
            raise ValueError('STATION_SERVICE_REQUEST_INVALID')
        action=request.get('action')
        if action == 'set-native-debug':
            if set(request) != {'action', 'enabled'} or type(request['enabled']) is not bool:
                raise ValueError('STATION_SERVICE_REQUEST_INVALID')
            if request['enabled'] and not callable(getattr(self.port, 'prepare_native', None)):
                raise ValueError('STATION_NATIVE_METHOD_UNSUPPORTED')
            self.native_debug_enabled = request['enabled']
            return {'native_debug_enabled': self.native_debug_enabled}
        if action in ('prepare-native', 'execute-native'):
            if not self.native_debug_enabled:
                raise ValueError('STATION_NATIVE_DEBUG_DISABLED')
            reason = request.get('debug_reason')
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
                raise ValueError('STATION_NATIVE_DEBUG_REASON_REQUIRED: use a CULS program for experiments')
        if action == 'run-logs':
            return self.run_logs(request)
        if action == 'prepare-native':
            if set(request) != {'action', 'entrypoint', 'files', 'mode', 'debug_reason'}:
                raise ValueError('STATION_SERVICE_REQUEST_INVALID')
            prepare = getattr(self.port, 'prepare_native', None)
            if not callable(prepare):
                raise ValueError('STATION_NATIVE_METHOD_UNSUPPORTED')
            require_idle()
            return {**prepare(request['entrypoint'], request['files'], request['mode']),
                    'execution_origin': 'native_debug', 'debug_reason': reason,
                    'experiment_verified': False}
        if action in ('physical-permission-status', 'set-physical-permission'):
            if self.physical_permission is None:
                if action == 'physical-permission-status':
                    return {'available': False, 'enabled': None}
                raise ValueError('STATION_PHYSICAL_PERMISSION_UNSUPPORTED')
            if action == 'physical-permission-status' and set(request) == {'action'}:
                return self.physical_permission()
            if (action == 'set-physical-permission' and set(request) == {'action', 'enabled'}
                    and type(request['enabled']) is bool):
                require_idle()
                return self.physical_permission(request['enabled'])
            raise ValueError('STATION_SERVICE_REQUEST_INVALID')
        if action=='describe':
            return {'available':self.port is not None,'native_debug_enabled':self.native_debug_enabled,'details':self.port.describe() if self.port else None,
                    'unsettled_request':(self.repository.unsettled() or [None])[0]}
        request_id=request.get('request_id')
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',request_id):
            raise ValueError('STATION_SERVICE_REQUEST_ID_REQUIRED')
        if action not in ('initialize','execute-native','status','cancel','native-logs'): raise ValueError('STATION_SERVICE_ACTION_INVALID')
        previous=self.repository.get(request_id)
        if previous:
            identity,state,result=previous
            if action in ('initialize', 'execute-native'):
                operation = 'native' if action == 'execute-native' else 'initialize'
                if (operation != identity.get('operation', 'initialize')
                        or any(request.get(k) != identity[k] for k in ('method_id', 'bundle_sha256'))
                        or operation == 'native' and (request.get('mode') != identity.get('mode')
                            or request.get('debug_reason') != identity.get('debug_reason', request.get('debug_reason')))):
                    raise ValueError('STATION_SERVICE_ID_CONFLICT')
            if action == 'native-logs':
                return self.native_logs(request_id, identity, request)
            if state in ('completed','rejected','cancelled'): return {'request_id':request_id,**result,'state':state,
                **({'execution_origin': 'native_debug', 'experiment_verified': False,
                    'debug_reason': identity.get('debug_reason')} if identity.get('operation') == 'native' else {})}
            if self.port is None or self.configuration.fingerprint!=identity['configuration_fingerprint']:
                raise ValueError('STATION_SERVICE_CONFIGURATION_CHANGED')
            if action == 'cancel':
                cancel = getattr(self.port, 'cancel', None)
                if not callable(cancel): raise ValueError('STATION_SERVICE_CANCELLATION_UNSUPPORTED')
                # Only settle after the driver has actually released its reservation.
                # A lost response leaves this record available for status/retry.
                return self.repository.settle(request_id,cancel(request_id,identity))
            try: result=self.port.inspect(request_id,identity)
            except Exception as error: result={'state':'unknown','diagnostic':type(error).__name__}
            return self.repository.settle(request_id,result)
        if action in ('status','cancel','native-logs'): raise ValueError('STATION_SERVICE_NOT_FOUND')
        if self.port is None: raise ValueError('STATION_SERVICE_UNSUPPORTED')
        if action == 'execute-native' and request.get('mode') not in ('physical', 'simulation'):
            raise ValueError('STATION_NATIVE_MODE_REQUIRED')
        if (action == 'initialize' or request.get('mode') == 'physical') and request.get('acknowledge_clearance') is not True:
            raise ValueError('OPERATOR_CLEARANCE_CONFIRMATION_REQUIRED')
        require_idle()
        identity={k:request.get(k) for k in ('method_id','bundle_sha256')}
        if action == 'execute-native':
            identity.update(operation='native', mode=request['mode'], debug_reason=reason)
        self.port.validate(identity)
        identity['configuration_fingerprint']=self.configuration.fingerprint
        self.repository.admit(request_id,identity)  # Committed before any possible dispatch.
        try: result=self.port.submit(request_id,identity)
        except Exception as error: result={'state':'unknown','diagnostic':type(error).__name__}
        return self.repository.settle(request_id,result)

    def native_logs(self, request_id, identity, request):
        logs = getattr(self.port, 'logs', None)
        if identity.get('operation') != 'native' or not callable(logs):
            raise ValueError('STATION_NATIVE_LOGS_UNSUPPORTED')
        if self.configuration.fingerprint != identity['configuration_fingerprint']:
            raise ValueError('STATION_SERVICE_CONFIGURATION_CHANGED')
        offset, limit, stream = request.get('offset', 0), request.get('limit', 65536), request.get('stream', 'receipt')
        if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 65536
                or stream not in ('receipt', 'trace')):
            raise ValueError('STATION_NATIVE_LOG_CURSOR_INVALID')
        return {'request_id': request_id, 'stream': stream,
                **logs(request_id, identity, offset, limit, stream)}

    def run_logs(self, request):
        """Resolve a persisted OS attempt before reading driver-owned output."""
        logs = getattr(self.port, 'operation_logs', None)
        if self.run_evidence is None or not callable(logs):
            raise ValueError('RUN_LOGS_UNSUPPORTED')
        if set(request) - {'action', 'run_id', 'attempt_id', 'offset', 'limit', 'stream'}:
            raise ValueError('RUN_LOGS_REQUEST_INVALID')
        run_id, attempt_id = request.get('run_id'), request.get('attempt_id')
        if not all(isinstance(value, str) and value for value in (run_id, attempt_id)):
            raise ValueError('RUN_LOGS_IDENTITY_REQUIRED')
        offset, limit, stream = request.get('offset', 0), request.get('limit', 65536), request.get('stream', 'receipt')
        if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 65536
                or stream not in ('receipt', 'trace')):
            raise ValueError('RUN_LOGS_CURSOR_INVALID')
        attempts = self.run_evidence(run_id)['attempts']
        attempt = next((item for item in attempts if item['attempt_id'] == attempt_id), None)
        if attempt is None:
            raise ValueError('RUN_LOGS_ATTEMPT_NOT_FOUND')
        value = logs(attempt_id, attempt['mode'], attempt['context'].get('description', {}), offset, limit, stream)
        return {**value, 'run_id': run_id, 'attempt_id': attempt_id, 'stream': stream}
