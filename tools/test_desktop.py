"""Local native E2E: Flutter -> real HTTP owners -> official simulator. No cloud CI."""
import json
import os
import shutil
import signal
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
    def run(self, with_hamilton=False, screenshots=None):
        with tempfile.TemporaryDirectory(prefix='culsma-native-e2e-') as directory:
            root = Path(directory)
            events = root/'flutter-events.jsonl'
            extra = []
            if screenshots:
                screenshots.mkdir(parents=True, exist_ok=True)
                extra = ['--dart-define=E2E_SCREENSHOTS=true', '--file-reporter=json:'+str(events)]
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
                    command = ['fvm','flutter','test','--reporter=expanded','integration_test/layout_test.dart','-d','macos',
                        '--dart-define=E2E_ORIGIN='+server.url,
                        '--dart-define=E2E_HAMILTON='+str(with_hamilton).lower(), *extra]
                    with subprocess.Popen(command, cwd=ROOT/'frontend/console', start_new_session=True) as process:
                        try:
                            exit_code = process.wait(timeout=240)
                        except (subprocess.TimeoutExpired, KeyboardInterrupt):
                            # fvm launches both the Flutter runner and a native window.
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                            raise
                    if screenshots and events.exists():
                        for line in events.read_text().splitlines():
                            message = json.loads(line).get('message', '')
                            if message.startswith('CULSMA_UI_FRAME '):
                                source = Path(json.loads(message.removeprefix('CULSMA_UI_FRAME ')))
                                if source.name not in ('saved-layout.png', 'hamilton-layout.png', 'hamilton-deck.png'):
                                    raise ValueError(f'Unexpected frame name: {source.name}')
                                shutil.move(source, screenshots/source.name)
                                source.parent.rmdir()
                    if exit_code:
                        raise SystemExit(exit_code)
                    assert resident.client.execute({'action':'configuration-status'})['active']['origin']['revision'] == 2
                    runs = resident.client.execute({'action':'runs'})['runs']
                    assert len(runs) == 1 and runs[0]['status'] == 'completed', runs
                    print('Native E2E passed: edited layout applied and transfer completed with registered evidence.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-hamilton', action='store_true', help='Also exercise the Hamilton profile and native export with the installed Hamilton driver')
    parser.add_argument('--screenshots', type=Path, help='Save frames from the native layout tests here')
    args = parser.parse_args()
    DesktopE2E().run(args.with_hamilton, args.screenshots)
