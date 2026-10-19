"""Bounded local JSON transport. Business behavior belongs to ResidentCommandInteractor."""
import json
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
        allowed = {'action','run_id','source','material_state','library_roots','request_id','configuration','configuration_origin','configuration_fingerprint','driver'}
        if not isinstance(payload, dict) or set(payload) - allowed or not isinstance(payload.get('action'), str):
            raise ValueError('HOST_REQUEST_INVALID')
        for key in ('run_id','source','material_state','request_id','configuration_fingerprint','driver'):
            if payload.get(key) is not None and (not isinstance(payload[key], str) or not payload[key]):
                raise ValueError('HOST_REQUEST_INVALID')
        if any(payload.get(key) is not None and not isinstance(payload[key],dict) for key in ['configuration','configuration_origin']):
            raise ValueError('HOST_REQUEST_INVALID')
        roots = payload.get('library_roots', [])
        if not isinstance(roots, list) or not all(isinstance(p, str) and p for p in roots):
            raise ValueError('HOST_REQUEST_INVALID')
        return ResidentCommand(payload['action'], payload.get('run_id'),
            Path(payload['source']) if payload.get('source') else None,
            Path(payload['material_state']) if payload.get('material_state') else None,
            tuple(Path(p) for p in roots), payload.get('request_id'),payload.get('configuration'),
            payload.get('configuration_origin'),payload.get('configuration_fingerprint'),payload.get('driver'))


class ResidentSocketAdapter:
    def __init__(self, path, commands):
        self.path, self.commands = Path(path), commands
        self.socket = None
        self.bound = False

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def handle_one(self):
        try:
            connection, _ = self.socket.accept()
        except socket.timeout:
            return
        with connection:
            connection.settimeout(2)
            try:
                request = ResidentProtocolAdapter.request(ResidentProtocolAdapter.receive(connection))
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
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(str(self.path))
            ResidentProtocolAdapter.send(connection, request)
            response = ResidentProtocolAdapter.receive(connection)
        if not response['ok']:
            raise ResidentAdmissionError(response['error'], response.get('diagnostics', ()))
        return response['result']
