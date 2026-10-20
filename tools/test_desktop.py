"""Local native E2E: Flutter -> real HTTP owners -> official simulator. No cloud CI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.console.http import ConsoleHTTPHarness, ConsoleProtocolHarness


class DesktopE2E:
    def run(self, with_hamilton=False):
        with tempfile.TemporaryDirectory(prefix='culsma-native-e2e-') as directory:
            root = Path(directory)
            with patch.dict(os.environ, {'CULSMA_OS_STATION_ROOT': str(root/'stations')}), ConsoleProtocolHarness(root, 'transfer') as resident:
                server = ConsoleApplicationFactory().build(ConsoleSettings(resident.endpoint, 0,
                    root/'drafts.sqlite3', ROOT/'examples/transfer', root/'programs'))
                # Explicit isolated test credential; production bootstrap remains a private pipe.
                with patch('culsma_os.auth.interactors.secrets.token_urlsafe', return_value='native-e2e-fixture-only'):
                    server.sessions.execute()
                headers = {'Authorization':'Bearer native-e2e-fixture-only','Origin':server.url,'Content-Type':'application/json'}
                with ConsoleHTTPHarness(server) as http:
                    status, _, body = http.request('POST','/api/v1/configuration/drafts',headers,
                        {'action':'create','title':'Native E2E station','driver':'opentrons-simulator',
                         'configuration':json.loads((ROOT/'examples/transfer/deck.json').read_text())})
                    assert status == 200, body
                    draft = body['data']['draft']
                    active = resident.client.execute({'action':'configuration-status'})
                    status, _, body = http.request('POST','/api/v1/configuration/activation',headers,
                        {'action':'apply','draft_id':draft['draft_id'],'revision':1,
                         'expected_fingerprint':active['active']['fingerprint'],'request_id':'native-e2e-setup'})
                    assert status == 200, body
                    resident.wait(lambda: resident.client.execute({'action':'configuration-status'})['receipt']['status']=='applied',30)
                    result = subprocess.run(['fvm','flutter','test','integration_test/layout_test.dart','-d','macos',
                        '--dart-define=E2E_ORIGIN='+server.url,
                        '--dart-define=E2E_HAMILTON='+str(with_hamilton).lower()], cwd=ROOT/'frontend/console', timeout=240)
                    if result.returncode:
                        raise SystemExit(result.returncode)
                    assert resident.client.execute({'action':'configuration-status'})['active']['origin']['revision'] == 2
                    runs = resident.client.execute({'action':'runs'})['runs']
                    assert len(runs) == 1 and runs[0]['status'] == 'completed', runs
                    print('Native E2E passed: edited layout applied and transfer completed with registered evidence.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-hamilton', action='store_true', help='Also exercise an installed offline Hamilton configuration profile')
    DesktopE2E().run(parser.parse_args().with_hamilton)
