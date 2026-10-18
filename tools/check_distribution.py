"""Check wheel entry points and sdist inputs without importing unpublished dependencies."""
import argparse
import configparser
from email.parser import BytesParser
from hashlib import sha256
import json
from pathlib import Path
import tarfile
import zipfile


class DistributionAudit:
    required_inputs = ('pyproject.toml', 'requirements/preview-constraints.txt',
                       'tools/distribution/manifest.json',
                       'tests/acceptance/manifests/protocols.json',
                       'tests/acceptance/manifests/resident.json',
                       'tests/architecture/module-map.json', 'tests/conftest.py',
                       'tests/support/paths.py', 'tools/build_preview_dependencies.py',
                       'examples/transfer/transfer.culs', 'examples/transfer/deck.json',
                       'tests/fixtures/driver_framework/opentrons/transfer.culs')

    def inspect(self, directory):
        wheels, sources = list(directory.glob('culsma_os-*.whl')), list(directory.glob('culsma_os-*.tar.gz'))
        if len(wheels) != 1 or len(sources) != 1:
            raise ValueError('DISTRIBUTION_ARTIFACTS_REQUIRED')
        wheel, source = wheels[0], sources[0]
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(metadata_names) != 1:
                raise ValueError('DISTRIBUTION_METADATA_REQUIRED')
            metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
            entries = configparser.ConfigParser()
            entries.read_string(archive.read(metadata_names[0].rsplit('/', 1)[0] + '/entry_points.txt').decode())
            if dict(entries['console_scripts']) != {'culsma-os': 'culsma_os.cli:CulsmaOSCLI.main'}:
                raise ValueError('DISTRIBUTION_CONSOLE_OWNERSHIP_INVALID')
            if (not entries.has_section('culsma.program_executors')
                    or entries.get('culsma.program_executors', 'opentrons-simulator', fallback=None)
                    != 'culsma_os.bootstrap:LanguageProgramExecutorFactory'):
                raise ValueError('DISTRIBUTION_HANDOFF_MISSING')
            code = {n: archive.read(n) for n in archive.namelist() if n.startswith('culsma_os/')}
        with tarfile.open(source) as archive:
            members = archive.getnames()
            prefix = members[0].split('/')[0] + '/'
            if any(prefix + path not in members for path in self.required_inputs):
                raise ValueError('DISTRIBUTION_SOURCE_INPUT_MISSING')
            if any('/run-artifacts/' in n or '/.venv/' in n for n in members):
                raise ValueError('DISTRIBUTION_LOCAL_STATE_INCLUDED')
            for path, payload in code.items():
                member = archive.extractfile(prefix + 'src/' + path)
                if member is None or member.read() != payload:
                    raise ValueError('DISTRIBUTION_CODE_MISMATCH')
            contract = json.load(archive.extractfile(prefix + 'tools/distribution/manifest.json'))
        dependencies = metadata.get_all('Requires-Dist') or []
        core = contract['sources']['core']
        required = core['distribution'] + '==' + core['artifact_version']
        if required not in [value.replace(' ', '') for value in dependencies]:
            raise ValueError('DISTRIBUTION_DEPENDENCY_CONTRACT_INVALID')
        return {'status': 'passed', 'runtime_imported': False,
                'scope': 'Archive structure only; does not claim runtime compatibility',
                'runtime_files_identical': len(code), 'requires_dist': dependencies,
                'artifacts': [{'name': p.name, 'sha256': sha256(p.read_bytes()).hexdigest()} for p in (wheel, source)]}

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--directory', type=Path, required=True)
        args = parser.parse_args()
        print(json.dumps(cls().inspect(args.directory), indent=2))


if __name__ == '__main__':
    DistributionAudit.main()
