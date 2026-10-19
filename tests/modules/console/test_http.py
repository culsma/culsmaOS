from hashlib import sha256
from importlib.resources import files

import pytest

from culsma_os.console.adapters.http import ConsoleHTTPServer
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from tests.support.console.http import ConsoleHTTPHarness, ResidentReadFixture
from tests.support.paths import ROOT


class TestConsoleHTTP:
    @pytest.fixture
    def console(self, tmp_path):
        resident = ResidentReadFixture()
        server = ConsoleHTTPServer(ConsoleSettings(tmp_path/'host.sock', 0), ConsoleCommandInteractor(resident))
        with ConsoleHTTPHarness(server) as harness:
            yield harness, resident

    def test_station_response_is_versioned_and_not_cached(self, console):
        harness, resident = console
        status, headers, result = harness.request('GET', '/api/v1/station')
        assert status == 200 and result['schema'] == 'culsma_console_v1'
        assert headers['Cache-Control'] == 'no-store'
        assert 'frame-ancestors' in headers['Content-Security-Policy']
        assert 'Access-Control-Allow-Origin' not in headers
        assert len(resident.calls) == 3

    @pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD', 'TRACE', 'CONNECT'])
    def test_http_methods_cannot_reach_resident(self, console, method):
        harness, resident = console
        status, headers, result = harness.request(method, '/api/v1/station')
        assert status == 405 and headers['Allow'] == 'GET'
        assert resident.calls == []

    @pytest.mark.parametrize('headers', [
        {'Host': 'foreign.example'}, {'Origin': 'https://foreign.example'},
        {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'},
    ])
    def test_foreign_browser_context_does_not_reach_resident(self, console, headers):
        harness, resident = console
        status, _, result = harness.request('GET', '/api/v1/station', headers)
        assert status == 403 and not result['ok']
        assert resident.calls == []

    @pytest.mark.parametrize('path', ['/.git/config', '/../README.md', '/%2e%2e/pyproject.toml',
                                      '/app.js/extra', '/api/v1/submit', '/api/v1/host-stop'])
    def test_unknown_paths_cannot_expose_files(self, console, path):
        harness, resident = console
        assert harness.request('GET', path)[0] == 404
        assert resident.calls == []

    def test_encoded_invalid_run_identifier_is_rejected(self, console):
        harness, resident = console
        assert harness.request('GET', '/api/v1/runs/a%2Fb')[0] == 400
        assert resident.calls == []

    def test_static_resources_are_packaged_and_allowlisted(self, console):
        harness, resident = console
        for path, mime in [('/', 'text/html'), ('/app.js', 'text/javascript'),
                           ('/interaction.js', 'text/javascript'), ('/style.css', 'text/css'), ('/assets/culsma-os-wordmark.png', 'image/png')]:
            status, headers, payload = harness.request('GET', path)
            assert status == 200 and headers['Content-Type'].startswith(mime) and payload
        for name in ['culsma-logo.png', 'culsma-os-wordmark.png']:
            packaged = files('culsma_os.console').joinpath('web', 'assets', name).read_bytes()
            assert sha256(packaged).digest() == sha256((ROOT/'assets'/name).read_bytes()).digest()
        assert resident.calls == []

    def test_missing_service_stays_missing(self, tmp_path):
        missing = tmp_path/'missing'/'host.sock'
        server = ConsoleApplicationFactory().build(ConsoleSettings(missing, 0))
        assert server.server_address[0] == '127.0.0.1'
        with ConsoleHTTPHarness(server) as harness:
            status, _, body = harness.request('GET', '/api/v1/station')
            assert status == 503 and body['error']['code'] == 'CONSOLE_HOST_UNAVAILABLE'
        assert not missing.parent.exists()

    @pytest.mark.parametrize('port', [-1, 65536, True, '8765'])
    def test_invalid_port_is_rejected_before_binding(self, tmp_path, port):
        with pytest.raises(ValueError, match='CONSOLE_PORT_INVALID'):
            ConsoleSettings(tmp_path/'host.sock', port)
