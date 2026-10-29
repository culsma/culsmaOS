"""Isolated native file browser -> reviewed installation snapshot -> OS execution."""
import dataclasses
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from culsma_os.console.providers import ConsoleApplicationFactory
from tests.support.integration.shared_setup import SharedSetupHarness


def run():
    flutter=os.environ.get('CULSMA_OS_FLUTTER','flutter')
    output=ROOT/'run-artifacts/native-files';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='culsma-native-files-') as directory:
        with SharedSetupHarness(Path(directory),submit=False,programs=True) as shared:
            installation=Path(directory)/'application';(installation/'examples').mkdir(parents=True)
            (installation/'README.txt').write_text('Native installation preview')
            (installation/'examples/transfer.culs').write_bytes(shared.source.read_bytes())
            server=shared.http.server;factory=ConsoleApplicationFactory()
            server.settings=dataclasses.replace(server.settings,file_root=installation,serve_frontend=False)
            server.file_reads=factory.build_files(server.settings,server.sessions.tokens,server.programs.source)
            server.programs.scopes['installation']=factory.installation_source(server.settings)
            server.sessions.tokens.token=None
            with patch('culsma_os.auth.interactors.secrets.token_urlsafe',return_value='native-files-fixture-only'):
                server.sessions.tokens.issue_console_session()
            with (output/'flutter-e2e.log').open('w') as log:
                result=subprocess.run([flutter,'test','integration_test/files_test.dart','-d','macos','--no-pub',
                    '--dart-define=E2E_ORIGIN='+shared.url],cwd=ROOT/'frontend/console',stdout=log,stderr=subprocess.STDOUT,timeout=120)
            assert 'Failed to update ui::AXTree' not in (output/'flutter-e2e.log').read_text(),'Native accessibility tree became invalid; see flutter-e2e.log'
            assert result.returncode==0,'See run-artifacts/native-files/flutter-e2e.log'
            runs=shared.client.execute({'action':'runs'})['runs']
            assert len(runs)==1 and runs[0]['status']=='completed',runs
            assert len(shared.backend.calls)==2
            print('Native Files E2E passed: installation root, preview, folder navigation, installation snapshot, double-click run and result; isolated device double.',flush=True)


if __name__=='__main__':run()
