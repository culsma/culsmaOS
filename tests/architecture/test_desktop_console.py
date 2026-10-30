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
    assert f"version: {version.replace('rc', '-rc.')}+" in source


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


def test_native_shell_keeps_credentials_and_business_authority_out_of_views():
    base=ROOT/'frontend/console/lib/features/console'
    assert {p.name for p in base.iterdir() if p.is_dir()}=={'interactor','model','repository','view'}
    views='\n'.join(p.read_text() for p in (base/'view').glob('*.dart'))
    assert not any(word in views for word in ['LocalConsoleApi','Authorization','Bearer ','dart:io','WebView','WKWebView'])
    repository=(base/'repository/pending_request_repository.dart').read_text()
    assert 'access_token' not in repository and 'renderer_access_token' not in repository
    controller=(base/'interactor/console_interactor.dart').read_text()
    assert "'action': 'start'" in controller and 'await requests!.save(payload)' in controller
    assert 'requests!.clear()' in controller
    bridge=(base/'interactor/renderer_interactor.dart').read_text()
    assert "'acknowledge'" in bridge and 'SchedulerBinding.instance.endOfFrame' in bridge
    assert not any(action in bridge for action in ["'action': 'start'","'action': 'confirm'","'action': 'cancel'"])


def test_native_mutations_keep_transport_and_human_confirmation_boundaries():
    root=ROOT/'frontend/console/lib/features/console'
    views='\n'.join(p.read_text() for p in (root/'view').glob('*.dart'))
    assert not any(value in views for value in ['/api/v1/', 'ConsoleMutationRepository(', 'Random.secure'])
    labware=(root/'interactor/labware_interactor.dart').read_text()
    assert "repository!.save('labware', payload)" in labware
    assert labware.index("repository!.save('labware', payload)") < labware.index("await api.command('/api/v1/configuration/activation', payload)")
    setup=(root/'interactor/setup_interactor.dart').read_text()
    assert "'/api/v1/setup/confirmation'" in setup and "acknowledged(id)" in setup
    renderer=(root/'interactor/renderer_interactor.dart').read_text()
    assert 'setup/confirmation' not in renderer and 'labware' not in renderer
    repository=(root/'repository/mutation_repository.dart').read_text()
    assert 'ConsoleApi' not in repository and 'dart:io' in repository
