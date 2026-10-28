"""Native position-edit/loading E2E with real OS owners and an isolated device double."""
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.integration.test_console_labware import native_station


def run():
    flutter=os.environ.get('CULSMA_OS_FLUTTER','fvm')
    command=[flutter] if Path(flutter).name=='flutter' else [flutter,'flutter']
    output=ROOT/'run-artifacts/native-operations';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-operations-') as directory, pytest.MonkeyPatch.context() as monkeypatch:
        station=native_station(Path(directory),monkeypatch)
        configuration=json.loads(station.context.config_path.read_text())
        configuration['well_positions']={'DWP96_E4':{f'{chr(65+r)}{c}':f'{chr(65+r)}{c}' for c in range(1,13) for r in range(8)}}
        station.context.config_path.write_text(json.dumps(configuration))
        station.source.write_text('let source=tube(capacity=60mL,load=[content(kind=formulation,type=buffer,code="BUFFER"):200uL]);let assay=plate(format="96well",capacity=2000uL);let destination=assay[A1];destination << [source:50uL];destination << [source:50uL];')
        station.program_root=Path(directory)/'programs';station.program_root.mkdir()
        (station.program_root/'transfer.culs').write_text(station.source.read_text())
        with station as shared:
            shared.http.server.settings=dataclasses.replace(shared.http.server.settings,serve_frontend=False)
            tokens=shared.http.server.sessions.tokens
            tokens.token=None
            with patch('culsma_os.auth.interactors.secrets.token_urlsafe',return_value='native-operations-fixture-only'):
                tokens.issue_console_session()
            with (output/'flutter-e2e.log').open('w') as log:
                result=subprocess.run(command+['test','integration_test/operations_test.dart','-d','macos','--no-pub',
                    '--dart-define=E2E_ORIGIN='+shared.url],cwd=ROOT/'frontend/console',stdout=log,stderr=subprocess.STDOUT,timeout=240)
            if result.returncode != 0:
                for row in shared.client.execute({'action':'runs'})['runs']:
                    record=shared.client.execute({'action':'status','run_id':row['run_id']})
                    print(json.dumps({'status':record['status'],'error':record.get('error'),'setup':record.get('result',{}).get('os',{}).get('setup')}),flush=True)
            assert result.returncode==0,'Native operations E2E failed; see run-artifacts/native-operations/flutter-e2e.log'
            runs=shared.client.execute({'action':'runs'})['runs']
            assert len(runs)==1 and runs[0]['status']=='completed',runs
            assert len(shared.backend.calls)==2
            print('Native E2E passed: diagram remove/place, one save each, loading plan, explicit confirmation and result. Real OS/HTTP; isolated device double, no instrument.',flush=True)

if __name__=='__main__':run()
