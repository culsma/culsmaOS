"""Verify downloaded compatibility wheels before pip installs them."""
import argparse
from email.parser import BytesParser
from hashlib import sha256
import json
from pathlib import Path
import zipfile


class CompatibilityBundleAudit:
    def inspect(self, directory, sources):
        if set(sources) != {'core', 'simulator'}:
            raise ValueError('COMPATIBILITY_SOURCE_SET_REQUIRED')
        records = []
        for role, spec in sources.items():
            name = spec['artifact']
            if Path(name).name != name or not name.endswith('.whl'):
                raise ValueError('COMPATIBILITY_ARTIFACT_NAME_INVALID')
            path = directory / name
            if not path.is_file():
                raise ValueError('COMPATIBILITY_ARTIFACT_MISSING')
            digest = sha256(path.read_bytes()).hexdigest()
            if digest != spec['artifact_sha256']:
                raise ValueError('COMPATIBILITY_ARTIFACT_HASH_MISMATCH')
            with zipfile.ZipFile(path) as wheel:
                names = [n for n in wheel.namelist() if n.endswith('.dist-info/METADATA')]
                if len(names) != 1:
                    raise ValueError('COMPATIBILITY_METADATA_REQUIRED')
                metadata = BytesParser().parsebytes(wheel.read(names[0]))
            if (metadata['Name'] != spec['distribution']
                    or metadata['Version'] != spec['artifact_version']):
                raise ValueError('COMPATIBILITY_ARTIFACT_IDENTITY_MISMATCH')
            records.append({'role': role, 'artifact': name, 'sha256': digest})
        return {'status': 'passed', 'artifacts': records, 'runtime_imported': False}

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--directory', type=Path, required=True)
        args = parser.parse_args()
        contract = Path(__file__).resolve().parents[1] / 'tools/distribution/manifest.json'
        sources = json.loads(contract.read_text())['sources']
        print(json.dumps(cls().inspect(args.directory, sources), indent=2))


if __name__ == '__main__':
    CompatibilityBundleAudit.main()
