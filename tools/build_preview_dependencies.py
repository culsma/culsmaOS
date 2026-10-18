"""Build private, commit-labelled dependency wheels without editing their repositories."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib


class PreviewDependencyBuilder:
    def validate_source(self, source, spec):
        revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        if revision != spec['revision']:
            raise ValueError('PREVIEW_SOURCE_REVISION_MISMATCH')
        dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True)
        if dirty:
            raise ValueError('PREVIEW_SOURCE_TRACKED_CHANGES')

    def stamp_metadata(self, text, spec):
        project = tomllib.loads(text)['project']
        if project['name'] != spec['distribution'] or project['version'] != spec['source_version']:
            raise ValueError('PREVIEW_SOURCE_METADATA_MISMATCH')
        expected = spec['source_version'] + '+g' + spec['revision'][:12]
        if spec['artifact_version'] != expected:
            raise ValueError('PREVIEW_ARTIFACT_IDENTITY_MISMATCH')
        # Restrict the edit to [project]; build-system and dependency constraints stay intact.
        sections = re.split(r'(?m)^(\[[^\n]+\])\s*$', text)
        position = sections.index('[project]') + 1
        sections[position], changed = re.subn(r'(?m)^(version\s*=\s*)[\"\'][^\"\']+[\"\']',
                                             lambda m: m[1] + json.dumps(expected), sections[position])
        if changed != 1:
            raise ValueError('PREVIEW_VERSION_FIELD_REQUIRED')
        return ''.join(sections)

    def build(self, sources, specs, output):
        if output.exists():
            raise ValueError('PREVIEW_OUTPUT_MUST_BE_NEW')
        if not sources or set(sources) != set(specs):
            raise ValueError('PREVIEW_SOURCE_SET_REQUIRED')
        for key, source in sources.items():
            self.validate_source(source, specs[key])
        output.mkdir(parents=True)
        records = []
        with tempfile.TemporaryDirectory(prefix='culsma-preview-build-') as temporary:
            for key, source in sources.items():
                directory = Path(temporary) / key
                directory.mkdir()
                archive = Path(temporary) / (key + '.tar')
                with archive.open('wb') as stream:
                    subprocess.run(['git', '-C', str(source), 'archive', specs[key]['revision']], stdout=stream, check=True)
                with tarfile.open(archive) as stream:
                    stream.extractall(directory, filter='data')
                project = directory / 'pyproject.toml'
                project.write_text(self.stamp_metadata(project.read_text(), specs[key]))
                epoch = subprocess.check_output(['git', '-C', str(source), 'show', '-s', '--format=%ct', specs[key]['revision']], text=True).strip()
                subprocess.run([sys.executable, '-m', 'build', '--wheel', '--no-isolation',
                                '--outdir', str(output.resolve()), str(directory)], check=True,
                               env={**os.environ, 'SOURCE_DATE_EPOCH': epoch})
                wheels = list(output.glob(specs[key]['distribution'].replace('-', '_') + '-*.whl'))
                if len(wheels) != 1:
                    raise ValueError('PREVIEW_ARTIFACT_NOT_UNIQUE')
                wheel = wheels[0]
                records.append({'role': key, 'revision': specs[key]['revision'],
                                'version': specs[key]['artifact_version'], 'artifact': wheel.name,
                                'sha256': sha256(wheel.read_bytes()).hexdigest()})
        (output / 'dependencies.json').write_text(json.dumps(records, indent=2) + '\n')
        return records

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--core', type=Path, required=True)
        parser.add_argument('--simulator', type=Path, required=True)
        parser.add_argument('--output', type=Path, required=True)
        args = parser.parse_args()
        contract = Path(__file__).resolve().parents[1] / 'design/distribution-contract.json'
        specs = json.loads(contract.read_text())['sources']
        cls().build({'core': args.core, 'simulator': args.simulator}, specs, args.output)


if __name__ == '__main__':
    PreviewDependencyBuilder.main()
