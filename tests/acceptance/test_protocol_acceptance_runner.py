from tests.support.paths import ROOT
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from tests.acceptance.protocols import ProtocolAcceptanceSuite
from tests.support.acceptance.protocol_acceptance_runner import ROOT, AcceptanceRunnerFixture


class TestProtocolAcceptanceRunner:
    def test_manifest_has_complete_protocol_matrix(self):
        suite=ProtocolAcceptanceSuite()
        assert len(suite.manifest['profiles'])==3
        assert sum(case['expected_cases'] for p in suite.manifest['profiles'] for case in p['cases'])==35
        assert {p['program'] for p in suite.manifest['profiles']}=={
            'examples/pcr-benchmark/protocol.culs','examples/magnetic-buffer-exchange/protocol.culs'}

    def test_report_matches_every_outcome_cell(self,tmp_path):
        suite=AcceptanceRunnerFixture().suite(tmp_path);path=tmp_path/'pytest.xml'
        AcceptanceRunnerFixture().xml(suite,path)
        report=suite.report(path,0)
        assert report['checks']=='passed' and report['test_count']==35 and report['outcome_cells']==9
        assert all(p['checks']=='passed' for p in report['profiles'])
        assert not report['errors']

    @pytest.mark.parametrize('problem',['failure','error','skipped','missing','duplicate','unexpected','exit'])
    def test_report_refuses_false_success(self,tmp_path,problem):
        suite=AcceptanceRunnerFixture().suite(tmp_path);path=tmp_path/'pytest.xml'
        AcceptanceRunnerFixture().xml(suite,path)
        tree=ET.parse(path);tests=tree.getroot().find('testsuite');first=tests.find('testcase')
        if problem in ('failure','error','skipped'):ET.SubElement(first,problem)
        elif problem=='missing':tests.remove(first)
        elif problem=='duplicate':tests.append(deepcopy(first))
        elif problem=='unexpected':ET.SubElement(tests,'testcase',classname='unexpected',name='test_not_selected')
        tree.write(path)
        assert suite.report(path,2 if problem=='exit' else 0)['checks']=='failed'

    @pytest.mark.parametrize('present',[False,True])
    def test_missing_or_malformed_junit_fails(self,tmp_path,present):
        suite=AcceptanceRunnerFixture().suite(tmp_path);path=tmp_path/'pytest.xml'
        if present:path.write_text('not XML')
        report=suite.report(path,0)
        assert report['checks']=='failed' and report['errors'][0].startswith('JUNIT_UNAVAILABLE')

    @pytest.mark.parametrize('problem',['profile','selector','outcome','count','boolean-count','external-input'])
    def test_invalid_manifest_rejects_before_running(self,tmp_path,problem):
        suite=AcceptanceRunnerFixture().suite(tmp_path);profiles=suite.manifest['profiles']
        if problem=='profile':profiles[1]['id']=profiles[0]['id']
        elif problem=='selector':profiles[1]['cases'][0]['test']=profiles[0]['cases'][0]['test']
        elif problem=='outcome':profiles[0]['cases'].pop()
        elif problem=='count':profiles[0]['cases'][0]['expected_cases']=0
        elif problem=='boolean-count':profiles[0]['cases'][0]['expected_cases']=True
        else:profiles[0]['program']='../outside.culs'
        with pytest.raises(ValueError):suite.validate_manifest()

    def test_snapshots_preserve_input_and_detect_changes(self,tmp_path):
        suite=AcceptanceRunnerFixture().suite(tmp_path);output=tmp_path/'output';output.mkdir()
        records=suite.snapshot_inputs(output)
        assert len(records)==9 and not suite.input_changes(records)
        original=(output/records[0]['snapshot']).read_bytes()
        source=suite.source_path(records[0]['source']);source.write_text('// changed')
        assert suite.input_changes(records)==[records[0]['source']]
        assert (output/records[0]['snapshot']).read_bytes()==original

    def test_run_retains_reports_and_refuses_existing_output(self,tmp_path,monkeypatch):
        suite=AcceptanceRunnerFixture().suite(tmp_path);output=tmp_path/'output'
        def execute(directory):
            AcceptanceRunnerFixture().xml(suite,directory/'pytest.xml')
            (directory/'pytest.log').write_text('test-only successful subprocess')
            return 0
        monkeypatch.setattr(suite,'execute_tests',execute)
        report=suite.run(output)
        assert report['checks']=='passed' and not report['input_changes']
        before=(output/'summary.json').read_bytes()
        with pytest.raises(FileExistsError):suite.run(output)
        assert (output/'summary.json').read_bytes()==before

    def test_run_failure_still_saves_summary(self,tmp_path,monkeypatch):
        suite=AcceptanceRunnerFixture().suite(tmp_path);output=tmp_path/'output'
        monkeypatch.setattr(suite,'execute_tests',lambda directory:2)
        report=suite.run(output)
        assert report['checks']=='failed' and (output/'summary.json').is_file()
        assert 'PYTEST_EXIT: 2' in report['errors']

    def test_input_drift_fails_even_when_all_assertions_pass(self,tmp_path,monkeypatch):
        suite=AcceptanceRunnerFixture().suite(tmp_path)
        def execute(directory):
            AcceptanceRunnerFixture().xml(suite,directory/'pytest.xml')
            suite.source_path(suite.manifest['profiles'][0]['configuration']).write_text('{}')
            return 0
        monkeypatch.setattr(suite,'execute_tests',execute)
        report=suite.run(tmp_path/'output')
        assert report['checks']=='failed' and 'ACCEPTANCE_INPUT_CHANGED' in report['errors']

    def test_runner_has_no_device_or_os_execution_logic(self):
        import ast
        source=(ROOT/'tests/acceptance/protocols.py').read_text();tree=ast.parse(source)
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any(name.startswith(('culsma','opentrons')) for name in imports if name)
        assert not any(isinstance(n,ast.FunctionDef) for n in tree.body)

