import ast
import json
import tomllib
from tests.support.paths import ROOT


def test_native_frontend_has_no_device_or_credential_bootstrap_bypass():
    root = ROOT/'frontend/console'
    source = '\n'.join(p.read_text() for p in (root/'lib').rglob('*.dart'))
    assert not any(value in source for value in ['culsma_opentrons', 'opentrons_', 'SerialPort', 'UsbDevice', '/api/v1/session', 'Process.start', 'Process.run'])
    assert 'followRedirects = false' in source and "uri.host != '127.0.0.1'" in source
    assert 'Semantics(' in source
    assert (root/'integration_test/layout_test.dart').exists()
    assert (root/'test/layout/golden_test.dart').exists()
    assert (root/'.fvmrc').is_file()


def test_native_and_backend_share_product_version():
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    source = (ROOT/'frontend/console/pubspec.yaml').read_text()
    assert f'version: {version}+' in source


def test_console_desktop_adapter_only_transports_processes():
    tree = ast.parse((ROOT/'src/culsma_os/console/adapters/desktop.py').read_text())
    names = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any('interactor' in name or 'repository' in name or 'auth' in name for name in names)
    text = (ROOT/'src/culsma_os/console/adapters/desktop.py').read_text()
    assert 'stdin=subprocess.PIPE' in text
    assert 'access_token' not in text
    for module in (ROOT/'src/culsma_os').iterdir():
        if module.name == 'console' or not module.is_dir(): continue
        assert not any('frontend/console' in p.read_text() for p in module.rglob('*.py'))
