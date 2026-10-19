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


    def test_local_html_links_detect_missing_targets(self, tmp_path):
        (tmp_path / 'assets').mkdir()
        (tmp_path / 'assets/logo.png').write_bytes(b'image')
        content = b'<img src="assets/logo.png"><a href="docs/removed.json">Old</a><a href="#top">Top</a><a href="https://example.com">External</a>'
        assert module.PublicTreeCheck().inspect_html_links(content, tmp_path / 'index.html', tmp_path) == ['docs/removed.json']

    def test_missing_html_link_fails_public_tree_check(self, tmp_path, monkeypatch):
        (tmp_path / 'index.html').write_text('<a href="removed.json">Old</a>')
        checker = module.PublicTreeCheck()
        monkeypatch.setattr(checker, 'files', lambda root: ['index.html'])
        assert checker.inspect(tmp_path)['errors'] == [
            {'path': 'index.html', 'error': 'LOCAL_LINK_MISSING', 'target': 'removed.json'}]

    @pytest.mark.parametrize('relative', ['assets/culsma-logo.png', 'assets/culsma-os-wordmark.png'])
    @pytest.mark.parametrize('changed', [False, True])
    def test_only_reviewed_shared_logo_bytes_are_accepted(self, tmp_path, monkeypatch, changed, relative):
        original = Path(__file__).resolve().parents[2] / relative
        target = tmp_path / relative
        target.parent.mkdir()
        target.write_bytes(b'changed image' if changed else original.read_bytes())
        checker = module.PublicTreeCheck()
        monkeypatch.setattr(checker, 'files', lambda root: [relative])
        result = checker.inspect(tmp_path)
        assert result['checks'] == ('failed' if changed else 'passed')
        assert result['errors'] == ([{'path': relative, 'error': 'BRAND_IMAGE_HASH_MISMATCH'}] if changed else [])
