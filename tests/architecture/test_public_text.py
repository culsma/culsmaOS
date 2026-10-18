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
