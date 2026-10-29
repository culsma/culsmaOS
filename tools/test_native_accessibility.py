"""Native AX regression with isolated in-memory supplies; no instrument access."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run():
    frontend = ROOT / 'frontend/console'
    output = ROOT / 'run-artifacts/native-accessibility'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='culsma-ax-') as temporary:
        definitions = Path(temporary) / 'defines.json'
        definitions.write_text(json.dumps({'E2E_PROFILE': base64.b64encode(
            (frontend / 'test/fixtures/profile.json').read_bytes()).decode()}))
        log_path = output / 'flutter-e2e.log'
        with log_path.open('w') as log:
            result = subprocess.run([
                os.environ.get('CULSMA_OS_FLUTTER', 'flutter'), 'test',
                'integration_test/supply_accessibility_test.dart', '-d', 'macos',
                '--no-pub', '--dart-define-from-file=' + str(definitions),
            ], cwd=frontend, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        assert result.returncode == 0, f'Native test failed: {log_path}'
        assert 'Failed to update ui::AXTree' not in log_path.read_text(), 'Invalid native AX tree'
        print('Native AX regression passed: 12 cancellations, acknowledged replacement, no automatic run.')


if __name__ == '__main__':
    run()
