"""Bounded local JSON transport. Business behavior belongs to ResidentCommandInteractor."""
import json
import hmac
import secrets
from culsma_os.platform_support import HostFileIO
import os
from pathlib import Path
import socket
import stat
from uuid import uuid4
from ..models import ResidentCommand, ResidentAdmissionError


class ResidentProtocolAdapter:
    max_bytes = 4 * 1024 * 1024

    @classmethod
    def receive(cls, connection):
        chunks = bytearray()
        while True:
            chunk = connection.recv(min(65536, cls.max_bytes + 1 - len(chunks)))
            if not chunk:
                raise ValueError('HOST_INCOMPLETE_MESSAGE')
            chunks.extend(chunk)
            if len(chunks) > cls.max_bytes:
                raise ValueError('HOST_MESSAGE_TOO_LARGE')
            if b'\n' in chunks:
                line, remainder = chunks.split(b'\n', 1)
                if remainder:
                    raise ValueError('HOST_ONE_MESSAGE_REQUIRED')
                return json.loads(line)

    @classmethod
    def send(cls, connection, payload):
        encoded = json.dumps(payload, ensure_ascii=False, default=str).encode() + b'\n'
        if len(encoded) > cls.max_bytes:
            raise ValueError('HOST_MESSAGE_TOO_LARGE')
        connection.sendall(encoded)

    @staticmethod
    def request(payload):
        allowed = {'action','run_id','source','material_state','library_roots','request_id','configuration','configuration_origin','configuration_fingerprint','driver','setup_fingerprint','setup_preferences','setup_acknowledged','setup_origin','labware_change','supply_change','supply_origin','developer_scenario','profile_request','workflow_enabled','workflow_revision'}
        allowed.update(('floor_plan_request','station_service_request'))
        if not isinstance(payload, dict) or set(payload) - allowed or not isinstance(payload.get('action'), str):
            raise ValueError('HOST_REQUEST_INVALID')
        for key in ('run_id','source','material_state','request_id','configuration_fingerprint','driver','developer_scenario'):
            if payload.get(key) is not None and (not isinstance(payload[key], str) or not payload[key]):
                raise ValueError('HOST_REQUEST_INVALID')
        if any(payload.get(key) is not None and not isinstance(payload[key],dict) for key in ['configuration','configuration_origin','labware_change','supply_change','profile_request','floor_plan_request','station_service_request']):
            raise ValueError('HOST_REQUEST_INVALID')
        if (payload.get('setup_fingerprint') is not None and not isinstance(payload['setup_fingerprint'], str)
                or payload.get('setup_preferences') is not None and not isinstance(payload['setup_preferences'], dict)
                or type(payload.get('setup_acknowledged', False)) is not bool):
            raise ValueError('HOST_REQUEST_INVALID')
        if payload.get('setup_origin') is not None and not isinstance(payload['setup_origin'], str):
            raise ValueError('HOST_REQUEST_INVALID')
        if (payload.get('workflow_enabled') is not None and type(payload['workflow_enabled']) is not bool
                or payload.get('workflow_revision') is not None and type(payload['workflow_revision']) is not int):
            raise ValueError('HOST_REQUEST_INVALID')
        roots = payload.get('library_roots', [])
        if not isinstance(roots, list) or not all(isinstance(p, str) and p for p in roots):
            raise ValueError('HOST_REQUEST_INVALID')
        if payload.get('supply_origin') is not None and not isinstance(payload['supply_origin'],str):
            raise ValueError('HOST_REQUEST_INVALID')
        return ResidentCommand(payload['action'], payload.get('run_id'),
            Path(payload['source']) if payload.get('source') else None,
            Path(payload['material_state']) if payload.get('material_state') else None,
            tuple(Path(p) for p in roots), payload.get('request_id'),payload.get('configuration'),
            payload.get('configuration_origin'),payload.get('configuration_fingerprint'),payload.get('driver'),
            payload.get('setup_fingerprint'),payload.get('setup_preferences'),payload.get('setup_acknowledged',False),payload.get('setup_origin'),payload.get('labware_change'),payload.get('supply_change'),payload.get('supply_origin'),payload.get('developer_scenario'),payload.get('profile_request'),
            workflow_enabled=payload.get('workflow_enabled'), workflow_revision=payload.get('workflow_revision'),
            floor_plan_request=payload.get('floor_plan_request'), station_service_request=payload.get('station_service_request'))


class ResidentSocketAdapter:
    def __init__(self, path, commands):
        self.path, self.commands = Path(path), commands
        self.socket = None
        self.bound = False
        self.transport_token = None

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            return self.open_windows()
        if self.path.exists() or self.path.is_symlink():
            if not stat.S_ISSOCK(self.path.lstat().st_mode):
                raise ValueError('HOST_SOCKET_PATH_OCCUPIED')
            self.path.unlink()  # Caller holds the endpoint ownership lease.
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.path))
        self.bound = True
        os.chmod(self.path, 0o600)
        self.socket.listen(16)
        self.socket.settimeout(0.1)

    def open_windows(self):
        # CPython on Windows has no AF_UNIX. Only loopback is bound; possession of
        # the owner-only endpoint file is required on every request.
        if self.path.exists() or self.path.is_symlink():
            LocalResidentEndpoint.read(self.path)
            self.path.unlink()  # Caller holds the endpoint ownership lease.
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(16)
        self.socket.settimeout(0.1)
        self.transport_token = secrets.token_hex(32)
        try:
            LocalResidentEndpoint.write(self.path, self.socket.getsockname()[1], self.transport_token)
            self.bound = True
        except BaseException:
            self.socket.close()
            raise

    def handle_one(self):
        try:
            connection, _ = self.socket.accept()
        except socket.timeout:
            return
        with connection:
            connection.settimeout(2)
            try:
                payload = ResidentProtocolAdapter.receive(connection)
                if self.transport_token is not None:
                    supplied = payload.pop('transport_auth', None) if isinstance(payload, dict) else None
                    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.transport_token):
                        raise ValueError('HOST_TRANSPORT_UNAUTHORIZED')
                request = ResidentProtocolAdapter.request(payload)
                result = self.commands.execute(request)
                response = {'ok': True, 'result': result}
            except Exception as error:
                response = {'ok': False, 'error': str(error) or type(error).__name__,
                            'diagnostics': getattr(error, 'diagnostics', ())}
            try:
                ResidentProtocolAdapter.send(connection, response)
            except (OSError, ValueError):
                pass  # Accepted work is durable even when the submitter disconnects.

    def close(self):
        if self.socket is not None:
            self.socket.close()
        if self.bound:
            self.path.unlink(missing_ok=True)
            self.bound = False


class ResidentClientAdapter:
    def __init__(self, path, timeout=30):
        self.path, self.timeout = Path(path), timeout

    def execute(self, payload):
        request = dict(payload)
        request.setdefault('request_id', str(uuid4()))
        if os.name == 'nt':
            endpoint = LocalResidentEndpoint.read(self.path)
            request['transport_auth'] = endpoint['token']
            family, address = socket.AF_INET, ('127.0.0.1', endpoint['port'])
        else:
            family, address = socket.AF_UNIX, str(self.path)
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(address)
            ResidentProtocolAdapter.send(connection, request)
            response = ResidentProtocolAdapter.receive(connection)
        if not response['ok']:
            raise ResidentAdmissionError(response['error'], response.get('diagnostics', ()))
        return response['result']


class LocalResidentEndpoint:
    @staticmethod
    def write(path, port, token):
        descriptor = HostFileIO.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | HostFileIO.O_NOFOLLOW, private=True)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump({'schema': 'culsma_local_endpoint_v1', 'port': port, 'token': token}, stream)

    @staticmethod
    def read(path):
        descriptor = HostFileIO.open(path, os.O_RDONLY | HostFileIO.O_NOFOLLOW | HostFileIO.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('HOST_SOCKET_PATH_OCCUPIED')
            raw = stream.read(1025)
        try:
            value = json.loads(raw)
            if (len(raw) > 1024 or set(value) != {'schema', 'port', 'token'}
                    or value['schema'] != 'culsma_local_endpoint_v1'
                    or type(value['port']) is not int or not 1 <= value['port'] <= 65535
                    or not isinstance(value['token'], str) or len(value['token']) != 64
                    or any(c not in '0123456789abcdef' for c in value['token'])):
                raise ValueError()
            return value
        except (ValueError, TypeError, KeyError):
            raise ValueError('HOST_SOCKET_PATH_OCCUPIED') from None
