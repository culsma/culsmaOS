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

    def test_browser_source_is_read_only_and_renders_text_safely(self):
        source = (ROOT/'src/culsma_os/console/web/app.js').read_text()
        assert 'innerHTML' not in source and 'eval(' not in source
        assert "textContent" in source
        assert not any(f"method: '{method}'" in source for method in ['POST', 'PUT', 'PATCH', 'DELETE'])
