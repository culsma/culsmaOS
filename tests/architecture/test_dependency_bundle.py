"""Downloaded compatibility assets must match both identity and immutable bytes."""
import importlib.util
from hashlib import sha256
from pathlib import Path
import zipfile

import pytest

from tests.support.paths import ROOT

spec = importlib.util.spec_from_file_location('dependency_bundle', ROOT / 'tools/verify_preview_dependencies.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestDependencyBundle:
    def bundle(self, directory, identity=None, metadata=True):
        sources = {}
        for role, distribution in [('core', 'culsma'), ('simulator', 'culsma-opentrons-simulator')]:
            name = distribution.replace('-', '_') + '-1.0.8+gtest-py3-none-any.whl'
            path = directory / name
            with zipfile.ZipFile(path, 'w') as wheel:
                wheel.writestr('payload.txt', 'fixed payload')
                if metadata:
                    name_value = 'other' if identity == 'name' else distribution
                    version = '0.0.0' if identity == 'version' else '1.0.8+gtest'
                    wheel.writestr('package.dist-info/METADATA', f'Name: {name_value}\nVersion: {version}\n')
            sources[role] = {'artifact': name, 'artifact_sha256': sha256(path.read_bytes()).hexdigest(),
                             'distribution': distribution, 'artifact_version': '1.0.8+gtest'}
        return sources

    def test_valid_assets_are_verified_without_importing_the_runtime(self, tmp_path):
        sources = self.bundle(tmp_path)
        result = module.CompatibilityBundleAudit().inspect(tmp_path, sources)
        assert result['status'] == 'passed' and result['runtime_imported'] is False
        assert {r['role'] for r in result['artifacts']} == {'core', 'simulator'}

    def test_changed_download_rejects_before_installation(self, tmp_path):
        sources = self.bundle(tmp_path)
        with (tmp_path / sources['core']['artifact']).open('ab') as payload:
            payload.write(b'changed')
        with pytest.raises(ValueError, match='COMPATIBILITY_ARTIFACT_HASH_MISMATCH'):
            module.CompatibilityBundleAudit().inspect(tmp_path, sources)

    @pytest.mark.parametrize('identity', ['name', 'version'])
    def test_matching_hash_cannot_substitute_another_distribution(self, tmp_path, identity):
        sources = self.bundle(tmp_path, identity)
        with pytest.raises(ValueError, match='COMPATIBILITY_ARTIFACT_IDENTITY_MISMATCH'):
            module.CompatibilityBundleAudit().inspect(tmp_path, sources)

    def test_missing_metadata_rejects(self, tmp_path):
        sources = self.bundle(tmp_path, metadata=False)
        with pytest.raises(ValueError, match='COMPATIBILITY_METADATA_REQUIRED'):
            module.CompatibilityBundleAudit().inspect(tmp_path, sources)

    def test_missing_file_rejects(self, tmp_path):
        sources = self.bundle(tmp_path)
        (tmp_path / sources['core']['artifact']).unlink()
        with pytest.raises(ValueError, match='COMPATIBILITY_ARTIFACT_MISSING'):
            module.CompatibilityBundleAudit().inspect(tmp_path, sources)

    @pytest.mark.parametrize('name', ['../outside.whl', '/outside.whl', 'archive.zip'])
    def test_manifest_cannot_read_outside_the_download_directory(self, tmp_path, name):
        sources = self.bundle(tmp_path)
        sources['core']['artifact'] = name
        with pytest.raises(ValueError, match='COMPATIBILITY_ARTIFACT_NAME_INVALID'):
            module.CompatibilityBundleAudit().inspect(tmp_path, sources)

    def test_incomplete_bundle_cannot_report_success(self, tmp_path):
        sources = self.bundle(tmp_path)
        sources.pop('simulator')
        with pytest.raises(ValueError, match='COMPATIBILITY_SOURCE_SET_REQUIRED'):
            module.CompatibilityBundleAudit().inspect(tmp_path, sources)
