"""The source preview has explicit dependency and source-data ownership."""
from hashlib import sha256
import json
import tomllib

import pytest

from tests.support.paths import ROOT


class TestDistribution:
    def test_metadata_requires_exact_committed_snapshots(self):
        project=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']
        contract=json.loads((ROOT/'design/distribution-contract.json').read_text())
        core,simulator=contract['sources']['core'],contract['sources']['simulator']
        assert project['dependencies']==[core['distribution']+'=='+core['artifact_version']]
        assert project['optional-dependencies']['simulator']==[simulator['distribution']+'=='+simulator['artifact_version']]
        assert '+g' in core['artifact_version'] and core['artifact_version']!='1.0.8'

    def test_console_names_remain_owned_by_each_package(self):
        project=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']
        assert set(project['scripts'])=={'culsma-os'}
        assert project['entry-points']['culsma.program_executors']['opentrons-simulator'].startswith('culsma_os.')

    def test_simulator_fixtures_are_fixed_and_owned_by_this_suite(self):
        fixture=ROOT/'tests/fixtures/driver_framework/opentrons'
        manifest=json.loads((fixture/'provenance.json').read_text())
        assert len(manifest['files'])==17
        for entry in manifest['files']:
            assert sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256']
        source=(ROOT/'tests/support/integration/cli_simulator.py').read_text()
        assert 'culsma_opentrons.__file__' not in source


class TestDistributionAudit:
    def archives(self, tmp_path, problem=None):
        import io
        import tarfile
        import zipfile
        directory=tmp_path/'dist';directory.mkdir()
        version='1.0.8' if problem=='dependency' else '1.0.8+gca7a0984d0b5'
        console='culsma' if problem=='console' else 'culsma-os'
        entries=f'[console_scripts]\n{console} = culsma_os.cli:CulsmaOSCLI.main\n'
        if problem!='handoff':
            entries+='[culsma.program_executors]\nopentrons-simulator = culsma_os.bootstrap:LanguageProgramExecutorFactory\n'
        metadata=f'Name: culsma-os\nVersion: 0.1.0\nRequires-Dist: culsma=={version}\n'
        with zipfile.ZipFile(directory/'culsma_os-0.1.0-py3-none-any.whl','w') as archive:
            archive.writestr('culsma_os-0.1.0.dist-info/METADATA',metadata)
            archive.writestr('culsma_os-0.1.0.dist-info/entry_points.txt',entries)
            archive.writestr('culsma_os/__init__.py','"""Runtime."""\n')
        import importlib.util
        spec=importlib.util.spec_from_file_location('distribution_audit',ROOT/'tools/check_distribution.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tarfile.open(directory/'culsma_os-0.1.0.tar.gz','w:gz') as archive:
            prefix=tarfile.TarInfo('culsma_os-0.1.0');prefix.type=tarfile.DIRTYPE;archive.addfile(prefix)
            for name in (*module.DistributionAudit.required_inputs,'src/culsma_os/__init__.py'):
                if problem=='input' and name=='tests/conftest.py':continue
                payload=(ROOT/name).read_bytes() if (ROOT/name).is_file() else b''
                if name=='src/culsma_os/__init__.py':payload=b'changed' if problem=='code' else b'"""Runtime."""\n'
                entry=tarfile.TarInfo('culsma_os-0.1.0/'+name);entry.size=len(payload);archive.addfile(entry,io.BytesIO(payload))
            if problem=='state':
                entry=tarfile.TarInfo('culsma_os-0.1.0/run-artifacts/private.json');entry.size=2;archive.addfile(entry,io.BytesIO(b'{}'))
        return module.DistributionAudit(),directory

    def test_valid_archives_do_not_import_runtime_dependencies(self,tmp_path):
        audit,directory=self.archives(tmp_path)
        result=audit.inspect(directory)
        assert result['status']=='passed' and result['runtime_imported'] is False
        assert result['runtime_files_identical']==1

    def test_missing_artifacts_reject(self,tmp_path):
        import pytest
        audit,directory=self.archives(tmp_path)
        next(directory.glob('*.whl')).unlink()
        with pytest.raises(ValueError,match='DISTRIBUTION_ARTIFACTS_REQUIRED'):
            audit.inspect(directory)

    @pytest.mark.parametrize('problem,diagnostic', [
        ('console','CONSOLE_OWNERSHIP_INVALID'),('handoff','HANDOFF_MISSING'),
        ('input','SOURCE_INPUT_MISSING'),('state','LOCAL_STATE_INCLUDED'),
        ('code','CODE_MISMATCH'),('dependency','DEPENDENCY_CONTRACT_INVALID')])
    def test_archive_contract_failures(self,tmp_path,problem,diagnostic):
        audit,directory=self.archives(tmp_path,problem)
        with pytest.raises(ValueError,match='DISTRIBUTION_'+diagnostic):
            audit.inspect(directory)
