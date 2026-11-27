"""Versioned HTTP boundary for the station's remote read operations."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import ConsoleReadError
from ..models import RemoteReadOperation, RemoteReadRequest


READ_PATH = '/v1/read'


class RemoteReadRequestAdapter:
    def __init__(self, reads):
        self.reads = reads

    def handle(self, raw_credential, payload):
        # Only typed read operations. Never forward arbitrary resident commands.
        if (not isinstance(payload, dict)
                or not {'station_id', 'operation'} <= set(payload)
                or set(payload) - {'station_id', 'operation', 'run_id'}):
            raise ValueError('REMOTE_READ_REQUEST_INVALID')
        request = RemoteReadRequest(payload['station_id'],
            RemoteReadOperation(payload['operation']), payload.get('run_id'))
        return self.reads.execute(raw_credential, request)


class RemoteReadHTTPServer(HTTPServer):
    """The HTTP origin is loopback only. A tunnel provides remote encryption."""

    def __init__(self, port, adapter):
        self.adapter = adapter
        super().__init__(('127.0.0.1', port), RemoteReadHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class RemoteReadHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Never write attacker-controlled paths, headers or payloads to logs.
        pass

    def do_POST(self):
        if self.path != READ_PATH:
            self.reply(404, {'error': 'REMOTE_ENDPOINT_NOT_FOUND'})
            return
        try:
            lengths = self.headers.get_all('Content-Length', [])
            if (len(lengths) != 1 or self.headers.get('Transfer-Encoding')
                    or not lengths[0].isascii() or not lengths[0].isdecimal()
                    or len(lengths[0]) > 4 or not 0 < int(lengths[0]) <= 4096
                    or self.headers.get_content_type() != 'application/json'):
                raise ValueError
            credentials = self.headers.get_all('Authorization', [])
            credential = credentials[0] if len(credentials) == 1 else ''
            payload = json.loads(self.rfile.read(int(lengths[0])).decode('utf-8'))
            result = self.server.adapter.handle(credential, payload)
        except ConsoleAccessError as error:
            self.reply(401 if error.kind == 'unauthenticated' else 403, {'error': error.code})
        except ConsoleReadError as error:
            status = {'not_found': 404, 'unavailable': 503}.get(error.kind, 502)
            self.reply(status, {'error': error.code})
        except (ValueError, RecursionError):
            self.reply(400, {'error': 'REMOTE_READ_REQUEST_INVALID'})
        except OSError:
            self.reply(503, {'error': 'REMOTE_STATION_UNAVAILABLE'})
        else:
            self.reply(200, result)

    def reply(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
