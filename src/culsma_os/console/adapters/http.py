"""Fixed-resource, loopback-only HTTP adapter for the local OS console."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import logging
from urllib.parse import unquote, urlsplit

from culsma_os.program_manager.models import ConsoleReadError, ConsoleReadRequest
from culsma_os.workspace_manager.models import StationConfigurationRequest, ConfigurationError
from culsma_os.auth.models import ConsoleAccessError


class ConsoleHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, settings, commands, configuration=None, sessions=None):
        self.commands, self.configuration, self.sessions = commands, configuration, sessions
        super().__init__(("127.0.0.1", settings.port), ConsoleHTTPHandler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class ConsoleHTTPHandler(BaseHTTPRequestHandler):
    server_version = "culsmaOS-console"
    sys_version = ""
    static_resources = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/style.css": ("style.css", "text/css; charset=utf-8"),
        "/assets/culsma-os-wordmark.png": ("assets/culsma-os-wordmark.png", "image/png"),
        "/assets/culsma-logo.png": ("assets/culsma-logo.png", "image/png"),
        "/favicon.ico": ("assets/culsma-logo.png", "image/png"),
    }

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def validate_context(self, api):
        hosts = self.headers.get_all("Host", [])
        authorities = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if len(hosts) != 1 or hosts[0] not in authorities:
            raise ConsoleReadError("CONSOLE_HOST_REJECTED", "forbidden")
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] != f"http://{hosts[0]}"):
            raise ConsoleReadError("CONSOLE_ORIGIN_REJECTED", "forbidden")
        if api and self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ConsoleReadError("CONSOLE_ORIGIN_REJECTED", "forbidden")

    def route(self, path):
        if path == "/api/v1/station":
            return ConsoleReadRequest("station")
        if path == "/api/v1/runs":
            return ConsoleReadRequest("runs")
        if path.startswith("/api/v1/runs/"):
            return ConsoleReadRequest("run", unquote(path[len("/api/v1/runs/"):]))
        raise ConsoleReadError("CONSOLE_ROUTE_NOT_FOUND", "not_found")

    def do_GET(self):
        try:
            url = urlsplit(self.path)
            self.validate_context(url.path.startswith("/api/"))
            if url.query or url.fragment or url.scheme or url.netloc:
                raise ConsoleReadError("CONSOLE_REQUEST_INVALID", "invalid_request")
            if url.path in self.static_resources:
                name, content_type = self.static_resources[url.path]
                payload = files("culsma_os.console").joinpath("web", name).read_bytes()
                self.respond(200, payload, content_type)
                return
            if url.path == '/api/v1/session' and self.server.sessions is not None:
                if self.headers.get('X-Culsma-Console') != '1' or self.headers.get('Sec-Fetch-Site') != 'same-origin':
                    raise ConsoleReadError('CONSOLE_BOOTSTRAP_CONTEXT_REJECTED','forbidden')
                result = self.server.sessions.execute()
                self.respond(200,json.dumps(result).encode())
                return
            if url.path in {'/api/v1/configuration/profiles','/api/v1/configuration/drafts'} and self.server.configuration is not None:
                action = 'profiles' if url.path.endswith('/profiles') else 'list'
                result = self.server.configuration.execute(self.headers.get('Authorization'),StationConfigurationRequest(action))
                self.respond(200,json.dumps({'schema':'culsma_configuration_v1','data':result}).encode())
                return
            result = self.server.commands.execute(self.route(url.path))
            self.respond(200, json.dumps(result.as_dict()).encode())
        except (ConsoleReadError,ConfigurationError,ConsoleAccessError) as error:
            status = {"forbidden": 403, "not_found": 404, "invalid_request": 400,
                      "read_only": 405, "unavailable": 503, "bad_response": 502, "unauthenticated":401, "conflict":409}[error.kind]
            self.respond(status, json.dumps({"schema": "culsma_console_v1", "ok": False,
                "error": {"code": error.code}}).encode())
        except Exception:
            logging.getLogger(__name__).exception("Console read failed")
            self.respond(500, b'{"ok":false,"error":{"code":"CONSOLE_INTERNAL_ERROR"}}')

    def configuration_request(self, payload):
        allowed = {'action','draft_id','revision','title','driver','configuration'}
        if not isinstance(payload,dict) or set(payload)-allowed or not isinstance(payload.get('action'),str):
            raise ConsoleReadError('CONSOLE_CONFIGURATION_REQUEST_INVALID','invalid_request')
        if any(payload.get(key) is not None and not isinstance(payload[key],str) for key in ['draft_id','title','driver']):
            raise ConsoleReadError('CONSOLE_CONFIGURATION_REQUEST_INVALID','invalid_request')
        if payload.get('revision') is not None and type(payload['revision']) is not int:
            raise ConsoleReadError('CONSOLE_CONFIGURATION_REQUEST_INVALID','invalid_request')
        if payload.get('configuration') is not None and not isinstance(payload['configuration'],dict):
            raise ConsoleReadError('CONSOLE_CONFIGURATION_REQUEST_INVALID','invalid_request')
        return StationConfigurationRequest(**payload)

    def do_POST(self):
        try:
            url = urlsplit(self.path)
            self.validate_context(True)
            if url.path != '/api/v1/configuration/drafts' or self.server.configuration is None:
                self.reject_method()
                return
            if url.query or url.fragment or url.scheme or url.netloc:
                raise ConsoleReadError('CONSOLE_REQUEST_INVALID','invalid_request')
            if self.headers.get('Origin') != 'http://'+self.headers.get('Host',''):
                raise ConsoleReadError('CONSOLE_ORIGIN_REJECTED','forbidden')
            lengths = self.headers.get_all('Content-Length',[])
            if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get('Transfer-Encoding') is not None:
                raise ConsoleReadError('CONSOLE_BODY_INVALID','invalid_request')
            length = int(lengths[0])
            if not 1 <= length <= 250000 or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                raise ConsoleReadError('CONSOLE_BODY_INVALID','invalid_request')
            try:
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('Incomplete body')
                payload = json.loads(body)
            except (ValueError,UnicodeError,RecursionError):
                raise ConsoleReadError('CONSOLE_JSON_INVALID','invalid_request') from None
            result = self.server.configuration.execute(self.headers.get('Authorization'),self.configuration_request(payload))
            self.respond(200,json.dumps({'schema':'culsma_configuration_v1','data':result}).encode())
        except (ConsoleReadError,ConfigurationError,ConsoleAccessError) as error:
            status = {'forbidden':403,'unauthenticated':401,'conflict':409,'not_found':404,'invalid_request':400}[error.kind]
            self.respond(status,json.dumps({'ok':False,'error':{'code':error.code}}).encode())
        except Exception:
            logging.getLogger(__name__).exception('Console configuration failed')
            self.respond(500,b'{"ok":false,"error":{"code":"CONSOLE_INTERNAL_ERROR"}}')

    def reject_method(self):
        self.respond(405, b'{"ok":false,"error":{"code":"CONSOLE_READ_ONLY"}}')

    do_PUT = reject_method
    do_PATCH = reject_method
    do_DELETE = reject_method
    do_OPTIONS = reject_method
    do_HEAD = reject_method
    do_TRACE = reject_method
    do_CONNECT = reject_method

    def respond(self, status, payload, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.send_header("Connection", "close")
        if status == 405:
            self.send_header("Allow", "GET")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, format, *args):
        pass
