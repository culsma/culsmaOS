import ast

from tests.support.paths import ROOT


class TestConsoleArchitecture:
    def test_console_transport_has_no_business_or_device_dependencies(self):
        root = ROOT/'src/culsma_os/console'
        for path in (root/'adapters').glob('*.py'):
            tree = ast.parse(path.read_text())
            names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            names += [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            assert not any(name.startswith(('sqlite3', 'culsma_opentrons', 'opentrons', 'culsma.runtime')) for name in names)
            assert not any('repositories' in name or 'bootstrap' in name for name in names)
            assert not any('Repository' in alias.name for node in ast.walk(tree)
                           if isinstance(node, ast.ImportFrom) for alias in node.names)
            calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
            assert not calls & {'advance', 'submit', 'resume', 'cancel', 'connect', 'build', 'register'}
        provider = (root/'providers.py').read_text()
        assert 'OSApplicationFactory' not in provider and 'build_resident_host' not in provider
        tree = ast.parse((ROOT/'src/culsma_os/program_manager/interactors/console.py').read_text())
        imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any('adapters' in name or 'console' in name for name in imports)

    def test_browser_uses_bounded_commands_and_renders_text_safely(self):
        source = '\n'.join(path.read_text() for path in (ROOT/'src/culsma_os/console/web').glob('*.js'))
        assert 'innerHTML' not in source and 'eval(' not in source
        assert "textContent" in source
        assert not any(f"'{method}'" in source for method in ['PUT','PATCH','DELETE'])
        assert "'/api/v1/configuration/drafts'" in source
        assert not any(f"'/api/v1/{action}'" in source for action in ['submit','pause','resume','cancel','host-stop'])


def test_shared_dom_has_no_execution_bypass():
    web = ROOT/'src/culsma_os/console/web'
    presentation = (web/'interaction.js').read_text()
    assert not any(value in presentation for value in ['fetch(', 'XMLHttpRequest', 'localStorage', 'sessionStorage',
        'Authorization', 'access_token', 'CallerContext', 'culsma_opentrons', 'WebSocket'])
    html = (web/'index.html').read_text()
    assert 'data-ui-schema="culsma_console_ui_v1"' in html
    assert 'aria-label="Last operation"' in html and 'aria-live="polite"' in html
    source = '\n'.join(path.read_text() for path in web.glob('*.js'))
    assert not any(value in source for value in ['dataset.token','dataset.credential','dataset.caller','window.execute','window.submit'])


def test_binding_page_has_shared_controls():
    source = (ROOT/'src/culsma_os/console/web/programs.js').read_text()
    assert "action:'program.check-bindings'" in source and "field:'/binding-draft'" in source
    assert 'snapshot_id:this.inspection.snapshot_id' in source
    assert 'this.bindingReview = null' in source


def test_binding_owner_uses_fixed_auth_and_no_foreign_repository():
    from culsma_os.auth.interactors import AuthorizedInteractor
    from culsma_os.workspace_manager.interactors import ProgramBindingInteractor
    assert ProgramBindingInteractor.execute is AuthorizedInteractor.execute
    assert ProgramBindingInteractor.required_capability == 'configuration:drafts'
    tree=ast.parse((ROOT/'src/culsma_os/workspace_manager/interactors.py').read_text())
    imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    assert not any('program_manager.repositories' in name or 'culsma_opentrons' in name for name in imports)



def test_activation_owner_and_adapter_boundaries():
    from culsma_os.auth.interactors import AuthorizedInteractor
    from culsma_os.lifecycle_manager.interactors import ConsoleActivationInteractor
    assert ConsoleActivationInteractor.execute is AuthorizedInteractor.execute
    assert ConsoleActivationInteractor.required_capability=='configuration:activate'
    tree=ast.parse((ROOT/'src/culsma_os/lifecycle_manager/interactors.py').read_text())
    imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    assert not any('workspace_manager.repositories' in name or 'culsma_opentrons' in name for name in imports)
    source=(ROOT/'src/culsma_os/console/web/activation.js').read_text()
    assert "action:'configuration.apply'" in source and "field:'/activation-confirmation'" in source
    assert 'setInterval' not in source


def test_labware_interface_is_owned_by_os_and_transport_delegates():
    from culsma_os.auth.interactors import AuthorizedInteractor
    from culsma_os.workspace_manager.interactors import LabwareConfigurationInteractor
    from culsma_os.driver_framework.models import LabwareEditorPort
    assert LabwareConfigurationInteractor.execute is AuthorizedInteractor.execute
    assert LabwareConfigurationInteractor.required_capability == 'configuration:drafts'
    assert set(('catalogue','prepare')) <= set(LabwareEditorPort.__dict__)
    source=(ROOT/'src/culsma_os/workspace_manager/interactors.py').read_text()
    assert 'culsma_driver_hamilton' not in source and 'culsma_opentrons' not in source
    source=(ROOT/'src/culsma_os/console/web/labware.js').read_text()
    assert 'Hamilton' not in source and '.lay' not in source.replace('.layout','')
    assert "action:'workstation.apply-labware'" in source


def test_experiment_preview_keeps_driver_and_run_mutations_outside_adapters():
    from culsma_os.auth.interactors import AuthorizedInteractor
    from culsma_os.program_manager.interactors.console_program import ConsoleProgramInteractor
    from culsma_os.driver_framework.models import WorkspaceCatalogueReadPort
    assert ConsoleProgramInteractor.execute is AuthorizedInteractor.execute
    assert ConsoleProgramInteractor.required_capability == 'programs:execute'
    assert 'execute' in WorkspaceCatalogueReadPort.__dict__
    tree = ast.parse((ROOT/'src/culsma_os/program_manager/interactors/setup.py').read_text())
    preview = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name=='RunSetupPreviewInteractor')
    calls = {node.func.attr for node in ast.walk(preview) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls & {'save','submit','acquire','confirm','connect','start','prepare_batch'}
    imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name.startswith(('culsma_driver_hamilton','culsma_opentrons')) for name in imports)
