from tests.support.paths import ROOT
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from tests.acceptance.resident import ResidentAcceptanceSuite
from tests.support.acceptance.resident_acceptance_runner import ROOT, ResidentRunnerFixture


class TestResidentAcceptanceRunner:
    def test_manifest_covers_mixed_protocol_and_station_boundaries(self):
        suite = ResidentAcceptanceSuite()
        assert len(suite.expected()) == 40
        assert {g['selector'] for g in suite.manifest['groups']} == {
            'tests/modules/program_manager/test_program_workspaces.py::TestProgramWorkspaces',
            'tests/integration/test_mixed_resident_protocols.py::TestMixedResidentProtocols',
            'tests/integration/test_resident_protocols.py::TestResidentProtocols',
            'tests/architecture/test_architecture.py::TestArchitecture'}
        assert suite.manifest['expected_audit_bundles'] == 15

    @pytest.mark.parametrize('problem',['failure','error','skipped','missing','duplicate','unexpected','exit','malformed'])
    def test_report_refuses_incomplete_or_unsuccessful_execution(self,tmp_path,problem):
        suite = ResidentRunnerFixture().suite(tmp_path); path = tmp_path/'results.xml'
        ResidentRunnerFixture().xml(suite,path)
        tree = ET.parse(path); tests = tree.getroot().find('testsuite'); first = tests.find('testcase')
        if problem in ('failure','error','skipped'): ET.SubElement(first,problem)
        elif problem == 'missing': tests.remove(first)
        elif problem == 'duplicate': tests.append(deepcopy(first))
        elif problem == 'unexpected': ET.SubElement(tests,'testcase',classname='other',name='test_other')
        tree.write(path)
        if problem == 'malformed': path.write_text('broken XML')
        assert suite.report(path,2 if problem == 'exit' else 0)['checks'] == 'failed'

    @pytest.mark.parametrize('problem',['selector','names','input','audit-count'])
    def test_invalid_manifest_rejects(self,tmp_path,problem):
        suite = ResidentRunnerFixture().suite(tmp_path)
        if problem == 'selector': suite.manifest['groups'][0]['selector'] = None
        elif problem == 'names': suite.manifest['groups'][0]['expected_tests'] *= 2
        elif problem == 'input': suite.manifest['inputs'][0] = '../outside'
        else: suite.manifest['expected_audit_bundles'] = True
        with pytest.raises(ValueError,match='ACCEPTANCE_'): suite.validate()

    def test_run_preserves_inputs_and_never_overwrites_old_artifacts(self,tmp_path,monkeypatch):
        fixture = ResidentRunnerFixture(); suite = fixture.suite(tmp_path)
        monkeypatch.setattr(suite,'execute',lambda output:fixture.execute(suite,output))
        output = tmp_path/'run'; report = suite.run(output)
        assert report['checks'] == 'passed' and report['test_count'] == 40
        assert len(report['audits']) == 15 and not report['input_changes']
        with pytest.raises(FileExistsError): suite.run(output)

    @pytest.mark.parametrize('problem',['missing-audit','invalid-audit','changed-source','deleted-source','changed-manifest'])
    def test_run_requires_original_inputs_and_complete_audits(self,tmp_path,monkeypatch,problem):
        fixture = ResidentRunnerFixture(); suite = fixture.suite(tmp_path)
        def execute(output):
            code = fixture.execute(suite,output)
            audit = next((output/'cases').rglob('resident-protocol-audit.json'))
            if problem == 'missing-audit': audit.unlink()
            elif problem == 'invalid-audit': audit.write_text('{}')
            elif problem == 'changed-source': suite.source(suite.manifest['inputs'][0]).write_text('changed')
            elif problem == 'deleted-source': suite.source(suite.manifest['inputs'][0]).unlink()
            else: suite.path.write_text('{}')
            return code
        monkeypatch.setattr(suite,'execute',execute)
        report = suite.run(tmp_path/'run')
        assert report['checks'] == 'failed'



class TestResidentFixtureSnapshots:
    def test_shared_fixtures_and_conftest_are_retained(self, tmp_path, monkeypatch):
        fixture = ResidentRunnerFixture()
        suite = fixture.suite(tmp_path)
        helper = suite.root / 'tests/support/program_manager/example.py'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text('class ExampleFixture: pass\n')
        conftest = suite.root / 'tests/conftest.py'
        conftest.write_text('# station isolation\n')
        monkeypatch.setattr(suite, 'execute', lambda output: fixture.execute(suite, output))
        output = tmp_path / 'run'
        result = suite.run(output)
        assert result['checks'] == 'passed'
        for source in (helper, conftest):
            relative = str(source.relative_to(suite.root))
            assert relative in {row['path'] for row in result['inputs']}
            assert (output / 'inputs' / relative).read_bytes() == source.read_bytes()
