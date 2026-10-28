"""Local macOS Flutter E2E with real OS/HTTP/MCP owners and a labelled device double."""
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import sqlite3
import threading
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.support.integration.shared_setup import SharedSetupHarness
from tests.support.integration.hamilton import HamiltonOperationTestBackend


class NativeShellGateBackend(HamiltonOperationTestBackend):
    """Only a local test double waits; no instrument or simulator process is involved."""
    def __init__(self):
        super().__init__()
        self.release=threading.Event()
        self.gates=0
    def execute(self,plan,attempt_id):
        if len(self.calls) in {0,2}:
            self.gates+=1
            self.release.clear()
            if not self.release.wait(120):raise RuntimeError('Native control test gate timed out')
        return super().execute(plan,attempt_id)



def run():
    flutter=os.environ.get('CULSMA_OS_FLUTTER','fvm')
    flutter_command=[flutter] if Path(flutter).name=='flutter' else [flutter,'flutter']
    output=ROOT/'run-artifacts/native-shell';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='culsma-native-shell-') as directory:
        shared=SharedSetupHarness(Path(directory),submit=False,programs=True)
        shared.backend=NativeShellGateBackend()
        configuration=json.loads(shared.context.config_path.read_text())
        configuration['execution']['tips']['available_positions']=[str(i) for i in range(1,9)]
        shared.context.config_path.write_text(json.dumps(configuration))
        nested=shared.program_root/'examples';nested.mkdir()
        (shared.program_root/'transfer.culs').rename(nested/'transfer.culs')
        shared.__enter__()
        try:
            execute_native(shared,flutter_command,output)
        finally:
            shared.backend.release.set()
            shared.__exit__(None,None,None)


def execute_native(shared,flutter_command,output):
    shared.http.server.settings=dataclasses.replace(shared.http.server.settings,serve_frontend=False)
    tokens=shared.http.server.sessions.tokens
    tokens.token=None
    with patch('culsma_os.auth.interactors.secrets.token_urlsafe',return_value='native-shell-console-fixture-only'):
        tokens.issue_console_session()
    with patch('culsma_os.auth.interactors.secrets.token_urlsafe',return_value='native-shell-renderer-fixture-only'):
        tokens.issue_renderer_session()
    headers={'Origin':shared.url,'Content-Type':'application/json','Authorization':'Bearer native-shell-console-fixture-only'}
    with (output/'flutter-e2e.log').open('w') as log:
        command=flutter_command+['test','integration_test/console_test.dart','-d','macos','--no-pub','--dart-define=E2E_ORIGIN='+shared.url]
        process=subprocess.Popen(command,cwd=ROOT/'frontend/console',stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+240
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError('Native E2E exited before renderer registration; see flutter-e2e.log')
                # Test coordination reads only the control queue; it does not fetch
                # checkpoints or alter the OS command/result path under test.
                with sqlite3.connect(shared.context.database_path) as db:
                    controls=db.execute("SELECT action FROM os_run_commands WHERE status='pending'").fetchall()
                if any(action in {'pause','cancel'} for (action,) in controls):
                    shared.backend.release.set()
                code,_,body=shared.http.request('POST','/api/v1/console/views/read',headers,{'action':'sessions'})
                if code==200 and any(row['online'] for row in body['data']['sessions']):break
                time.sleep(.5)
            else:raise TimeoutError('Native renderer registration timed out')
            print('Native renderer online; checking real MCP open_view',flush=True)
            env={**os.environ,'PYTHONPATH':os.environ['CULSMA_OS_MCP_SDK_PATH']+':'+str(ROOT/'src')}
            result=subprocess.run([sys.executable,'-m','tests.support.console.view_mcp_client',str(shared.endpoint),'system_info','-','native-shell-info'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=35)
            assert result.returncode==0,result.stderr
            assert json.loads(result.stdout)['status']=='displayed',result.stdout
            assert process.wait(timeout=50)==0,'Native E2E failed; see flutter-e2e.log'
            runs=shared.client.execute({'action':'runs'})['runs']
            assert len(runs)==2 and sorted(row['status'] for row in runs)==['cancelled','completed'],runs
            assert len(shared.backend.calls)==3
            with sqlite3.connect(shared.context.database_path) as db:
                commands=db.execute('SELECT action,status FROM os_run_commands').fetchall()
            assert sorted(commands)==[('cancel','applied'),('pause','applied'),('resume','applied')],commands
            print('Native shell E2E passed: nested file double-click, pause/resume/cancel with applied receipts, result, restore, MCP display receipt; device backend was an isolated test double.',flush=True)
        finally:
            shared.backend.release.set()
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':run()
