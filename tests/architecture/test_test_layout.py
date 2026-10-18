"""Test ownership and fixture boundaries must survive future additions."""
import ast
from pathlib import Path

from tests.support.paths import ROOT


class TestTestLayout:
    def test_collected_files_have_explicit_ownership(self):
        assert not list((ROOT / 'tests').glob('test_*.py'))
        owners = {p.name for p in (ROOT / 'src/culsma_os').iterdir() if p.is_dir() and p.name != '__pycache__'}
        for path in (ROOT / 'tests').rglob('test_*.py'):
            parts = path.relative_to(ROOT / 'tests').parts
            assert parts[0] in {'modules', 'integration', 'architecture', 'acceptance'}, path
            if parts[0] == 'modules':
                assert parts[1] in owners, path

    def test_tests_and_fixtures_do_not_import_collected_modules(self):
        for path in (ROOT / 'tests').rglob('*.py'):
            tree = ast.parse(path.read_text())
            nodes = list(ast.walk(tree))
            for value in list(nodes):
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and '\n' in value.value:
                    try:
                        nodes.extend(ast.walk(ast.parse(value.value)))
                    except SyntaxError:
                        pass
            for node in nodes:
                if isinstance(node, ast.ImportFrom):
                    assert node.module != 'tests.support', path
                    assert not any(part.startswith('test_') for part in (node.module or '').split('.')), path
                elif isinstance(node, ast.Import):
                    assert not any(part.startswith('test_') for alias in node.names for part in alias.name.split('.')), path
