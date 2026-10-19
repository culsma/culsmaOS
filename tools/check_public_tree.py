"""Validate English public text, including entity-encoded SVG/HTML labels."""
import argparse
import html
import json
from pathlib import Path
import re
import subprocess


class PublicTreeCheck:
    internal_docs = ('docs/module/', 'docs/evidence/', 'docs/archive/',
                     'docs/release/', 'docs/contracts/', 'design/')

    cjk = re.compile(r'[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]')

    def inspect_text(self, content, suffix):
        text = content.decode('utf-8')
        if suffix in {'.svg', '.html', '.htm'}:
            text = html.unescape(text)
        return [number for number, line in enumerate(text.splitlines(), 1) if self.cjk.search(line)]

    def files(self, root):
        output = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root)
        return sorted({name for name in output.decode().split('\0') if name and (root / name).is_file()})

    def inspect(self, root):
        problems, scanned, images = [], 0, 0
        for name in self.files(root):
            path = root / name
            if (name.startswith(self.internal_docs)
                    or (name.startswith('docs/') and re.search(r'20\d{6}', name))):
                problems.append({'path': name, 'error': 'INTERNAL_RECORD_IN_PUBLIC_TREE'})
            if path.suffix == '.png':
                images += 1
                if not path.with_suffix('.svg').is_file():
                    problems.append({'path': name, 'error': 'PNG_SOURCE_SVG_MISSING'})
                continue
            try:
                lines = self.inspect_text(path.read_bytes(), path.suffix)
            except UnicodeDecodeError:
                problems.append({'path': name, 'error': 'UNREVIEWED_BINARY_FILE'})
                continue
            scanned += 1
            if lines:
                problems.append({'path': name, 'error': 'NON_ENGLISH_CJK_TEXT', 'lines': lines})
        return {'checks': 'failed' if problems else 'passed', 'text_files': scanned,
                'png_with_svg_source': images, 'errors': problems}

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
        args = parser.parse_args()
        result = cls().inspect(args.root.resolve())
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['checks'] == 'passed' else 1)


if __name__ == '__main__':
    PublicTreeCheck.main()
