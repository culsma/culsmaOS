"""Native editor acceptance over real files, Auth, HTTP and Culsma compilation; no device doubles."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.console.models import ConsoleSettings


def run():
    output=ROOT/'run-artifacts/native-editor';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='culsma-editor-') as directory:
        temporary=Path(directory);home=temporary/'Home';programs=home/'projects';programs.mkdir(parents=True)
        source=temporary/'protocol.culs';source.write_text('let sample=tube(capacity=200uL);return sample;')
        settings=ConsoleSettings(temporary/'unused.sock',0,temporary/'drafts.sqlite3',programs,temporary/'snapshots',home,serve_frontend=False)
        server=ConsoleApplicationFactory().build(settings)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            environment={**os.environ,'CULSMA_EDITOR_TEST_ORIGIN':server.url,
                'CULSMA_EDITOR_TEST_TOKEN':server.sessions.tokens.issue_console_session(),
                'CULSMA_EDITOR_TEST_SOURCE':str(source),'CULSMA_EDITOR_TEST_ROOT':str(programs)}
            flutter=os.environ.get('CULSMA_OS_FLUTTER','flutter')
            with (output/'flutter-e2e.log').open('w') as log:
                result=subprocess.run([flutter,'test','integration_test/editor_test.dart','-d','macos','--no-pub'],
                    cwd=ROOT/'frontend/console',env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=240)
            log_text=(output/'flutter-e2e.log').read_text()
            assert 'Failed to update ui::AXTree' not in log_text, 'Native accessibility tree failed; inspect flutter-e2e.log'
            assert 'Lost connection to device' not in log_text, 'Native App connection was lost; inspect flutter-e2e.log'
            assert result.returncode==0,'Native editor E2E failed; see run-artifacts/native-editor/flutter-e2e.log'
            assert not settings.socket_path.exists()
            print('Native editor acceptance passed: native context menu, actual file drops and limits, create/edit/save/Save As, Culsma diagnostics, quiet refresh, reload protection and concurrent edits. No resident or instruments started.')
        finally:server.shutdown();thread.join(5);server.server_close()


if __name__=='__main__':run()
