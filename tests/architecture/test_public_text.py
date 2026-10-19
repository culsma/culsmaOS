"""Public text validation must inspect decoded labels, not only raw bytes."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('check_public_tree', Path(__file__).resolve().parents[2] / 'tools/check_public_tree.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestPublicText:
    @pytest.mark.parametrize('suffix,content', [
        ('.md', chr(0x4E2D).encode()),
        ('.md', chr(0x3002).encode()),
        ('.md', chr(0xFF1B).encode()),
        ('.svg', b'<text>&#20013;</text>'),
        ('.html', b'<p>&#x4e2d;</p>'),
    ])
    def test_cjk_is_detected_after_entity_decoding(self, suffix, content):
        assert module.PublicTreeCheck().inspect_text(content, suffix) == [1]

    def test_scientific_unicode_is_allowed(self):
        assert module.PublicTreeCheck().inspect_text('20 \u00b5L, \u03b1 = 0.5'.encode(), '.md') == []


    @pytest.mark.parametrize('relative', [
        'docs/evidence/check.json', 'docs/contracts/check.json',
        'docs/archive/check.json', 'docs/release/check.json',
        'docs/check-20261018.json',
    ])
    def test_internal_records_are_rejected(self, tmp_path, monkeypatch, relative):
        path = tmp_path / relative
        path.parent.mkdir(parents=True)
        path.write_text('{}')
        checker = module.PublicTreeCheck()
        monkeypatch.setattr(checker, 'files', lambda root: [relative])
        result = checker.inspect(tmp_path)
        assert result['checks'] == 'failed'
        assert result['errors'] == [{'path': relative, 'error': 'INTERNAL_RECORD_IN_PUBLIC_TREE'}]

    def test_current_documentation_is_allowed(self, tmp_path, monkeypatch):
        path = tmp_path / 'docs/development.md'
        path.parent.mkdir()
        path.write_text('# Development\n')
        checker = module.PublicTreeCheck()
        monkeypatch.setattr(checker, 'files', lambda root: ['docs/development.md'])
        assert checker.inspect(tmp_path)['checks'] == 'passed'
