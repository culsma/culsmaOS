"""Validate English public text, including entity-encoded SVG/HTML labels."""
import argparse
import html
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


class LocalHTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {'href', 'src'} and value:
                self.references.append(value)


class PublicTreeCheck:
    brand_images = {
        'assets/culsma-logo.png':
            'cb3c56f139b7473c84be44adcbe1c58f035ec8428b36393bb64914692a8f9d95',
        'assets/culsma-os-wordmark.png':
            '67f67511aa2104511f99b210612bf750f8a195879e8f5050a9b655c12b2c01c4',
    }

    brand_images.update({
        "src/culsma_os/console/web/assets/culsma-logo.png": brand_images["assets/culsma-logo.png"],
        "src/culsma_os/console/web/assets/culsma-os-wordmark.png": brand_images["assets/culsma-os-wordmark.png"],
    })

    internal_docs = ('docs/module/', 'docs/evidence/', 'docs/archive/',
                     'docs/release/', 'docs/contracts/', 'design/')

    cjk = re.compile(r'[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]')

    def inspect_text(self, content, suffix):
        text = content.decode('utf-8')
        if suffix in {'.svg', '.html', '.htm'}:
            text = html.unescape(text)
        return [number for number, line in enumerate(text.splitlines(), 1) if self.cjk.search(line)]

    def inspect_html_links(self, content, path, root):
        parser = LocalHTMLLinks()
        parser.feed(content.decode('utf-8'))
        missing = []
        for reference in parser.references:
            url = urlsplit(reference)
            if url.scheme or url.netloc or not url.path:
                continue
            relative = unquote(url.path)
            target = root / relative.lstrip('/') if relative.startswith('/') else path.parent / relative
            if not target.exists():
                missing.append(reference)
        return missing

    def files(self, root):
        output = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root)
        return sorted({name for name in output.decode().split('\0') if name and (root / name).is_file()})

    def inspect(self, root):
        problems, scanned, images, brands = [], 0, 0, 0
        for name in self.files(root):
            path = root / name
            if (name.startswith(self.internal_docs)
                    or (name.startswith('docs/') and re.search(r'20\d{6}', name))):
                problems.append({'path': name, 'error': 'INTERNAL_RECORD_IN_PUBLIC_TREE'})
            if path.suffix == '.png':
                if name in self.brand_images:
                    if sha256(path.read_bytes()).hexdigest() != self.brand_images[name]:
                        problems.append({'path': name, 'error': 'BRAND_IMAGE_HASH_MISMATCH'})
                    else:
                        brands += 1
                    continue
                images += 1
                if not path.with_suffix('.svg').is_file():
                    problems.append({'path': name, 'error': 'PNG_SOURCE_SVG_MISSING'})
                continue
            try:
                content = path.read_bytes()
                lines = self.inspect_text(content, path.suffix)
                if path.suffix in {'.html', '.htm'}:
                    problems.extend({'path': name, 'error': 'LOCAL_LINK_MISSING', 'target': target}
                                    for target in self.inspect_html_links(content, path, root))
            except UnicodeDecodeError:
                problems.append({'path': name, 'error': 'UNREVIEWED_BINARY_FILE'})
                continue
            scanned += 1
            if lines:
                problems.append({'path': name, 'error': 'NON_ENGLISH_CJK_TEXT', 'lines': lines})
        return {'checks': 'failed' if problems else 'passed', 'text_files': scanned,
                'png_with_svg_source': images, 'reviewed_brand_images': brands, 'errors': problems}

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
