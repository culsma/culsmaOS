from http.client import HTTPConnection
import socket

import pytest

pytest.importorskip('mcp.server.mcpserver')

from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.console.models import ConsoleSettings
from culsma_os.remote_access.desktop import DesktopRemoteAccess


def test_pairing_survives_restart_and_revoke_closes_access(tmp_path):
    tokens = TokenInteractor(SessionCredentialRepository())
    local = 'Bearer ' + tokens.issue_console_session()
    automation = 'Bearer ' + tokens.issue_automation_session()
    settings = ConsoleSettings(tmp_path / 'station.endpoint', drafts_path=tmp_path / 'drafts.sqlite3',
                               program_store=tmp_path / 'programs', home_path=tmp_path)
    grants = tmp_path / 'grants'
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]

    def request(credential):
        connection = HTTPConnection('127.0.0.1', port, timeout=2)
        try:
            connection.request('POST', '/mcp',
                               '{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
                               {'Authorization': 'Bearer ' + credential,
                                'Accept': 'application/json, text/event-stream',
                                'Content-Type': 'application/json'})
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    access = DesktopRemoteAccess(tokens, settings, 'desktop', grants, port)
    try:
        with pytest.raises(ConsoleAccessError, match='CONSOLE_CAPABILITY_DENIED'):
            access.execute(automation, {'action': 'enable'})
        result = access.execute(local, {'action': 'pair', 'name': 'mac-test'})
        assert not result['enabled']
        token = result['token']
        pairing = result['pairings'][0]
        assert token not in next(grants.glob('*.json')).read_text()
        assert access.execute(local, {'action': 'enable'})['enabled']
        assert request(token) == 200
        access.close()
        access = DesktopRemoteAccess(tokens, settings, 'desktop', grants, port)
        access.restore()
        assert access.execute(local, {'action': 'status'})['enabled']
        assert request(token) == 200
        assert not access.execute(local, {'action': 'disable'})['enabled']
        # Some Windows configurations time out the loopback SYN instead of
        # reporting a refusal within the client's connection deadline.
        with pytest.raises((ConnectionRefusedError, TimeoutError)):
            request(token)
    finally:
        access.close()

    access = DesktopRemoteAccess(tokens, settings, 'desktop', grants, port)
    try:
        access.restore()
        status = access.execute(local, {'action': 'status'})
        assert status == {'enabled': False, 'port': port, 'pairings': [pairing]}
        assert access.execute(local, {'action': 'enable'})['enabled']
        assert request(token) == 200
        assert not access.execute(local, {'action': 'unpair', 'id': pairing['id']})['pairings']
        assert request(token) == 401
    finally:
        access.close()
