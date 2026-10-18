"""Run the fixed protocol acceptance matrix through its owning pytest cases."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


class ProtocolAcceptanceSuite:
    outcomes = frozenset({'completed', 'rejected_before_actions', 'unknown_isolated'})

    def __init__(self, root=None, manifest=None):
        self.root = Path(root or Path(__file__).resolve().parents[2]).resolve()
        self.manifest_path = Path(manifest or self.root / 'design/protocol-acceptance-suite.json')
        self.manifest_content = self.manifest_path.read_bytes()
        self.manifest = json.loads(self.manifest_content)
        self.validate_manifest()

    def source_path(self, relative):
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError('ACCEPTANCE_RELATIVE_INPUT_REQUIRED')
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError(f'ACCEPTANCE_INPUT_UNAVAILABLE: {relative}')
        return path

    def validate_manifest(self):
        if self.manifest.get('schema') != 'culsma_protocol_acceptance_suite_v1':
            raise ValueError('ACCEPTANCE_SCHEMA_UNSUPPORTED')
        profiles = self.manifest.get('profiles')
        if not isinstance(profiles, list) or not profiles:
            raise ValueError('ACCEPTANCE_PROFILES_REQUIRED')
        identities, selectors = set(), set()
        for profile in profiles:
            identity = profile.get('id')
            if (not isinstance(identity, str) or not identity or not identity.replace('-', '_').isidentifier()
                    or identity in identities):
                raise ValueError('ACCEPTANCE_PROFILE_ID_INVALID')
            identities.add(identity)
            for role in ('program', 'configuration', 'expected'):
                self.source_path(profile.get(role))
            cases = profile.get('cases', [])
            if len(cases) != 3 or {case.get('outcome') for case in cases} != self.outcomes:
                raise ValueError('ACCEPTANCE_OUTCOME_MATRIX_INCOMPLETE')
            for case in cases:
                count = case.get('expected_cases')
                if type(count) is not int or count < 1:
                    raise ValueError('ACCEPTANCE_CASE_COUNT_INVALID')
                selector = case.get('test', '')
                parts = selector.split('::')
                if (len(parts) != 3 or not parts[0].startswith('tests/') or not parts[0].endswith('.py')
                        or not parts[1].isidentifier() or not parts[2].startswith('test_')
                        or not parts[2].isidentifier() or selector in selectors):
                    raise ValueError('ACCEPTANCE_TEST_SELECTOR_INVALID')
                self.source_path(parts[0])
                selectors.add(selector)

    def case_key(self, selector):
        file, owner, method = selector.split('::')
        return (file.removesuffix('.py').replace('/', '.') + '.' + owner, method)

    def snapshot_inputs(self, directory):
        records = []
        for profile in self.manifest['profiles']:
            folder = directory / 'inputs' / profile['id']
            folder.mkdir(parents=True)
            for role in ('program', 'configuration', 'expected'):
                source = self.source_path(profile[role])
                content = source.read_bytes()
                target = folder / source.name
                target.write_bytes(content)
                records.append({'profile': profile['id'], 'role': role, 'source': profile[role],
                    'sha256': sha256(content).hexdigest(), 'snapshot': str(target.relative_to(directory))})
        (directory / 'inputs/manifest.json').write_bytes(self.manifest_content)
        return records

    def input_changes(self, records):
        changes = []
        for record in records:
            try:
                unchanged = sha256(self.source_path(record['source']).read_bytes()).hexdigest() == record['sha256']
            except (OSError, ValueError):
                unchanged = False
            if not unchanged:
                changes.append(record['source'])
        return sorted(set(changes))

    def execute_tests(self, directory):
        selectors = [case['test'] for p in self.manifest['profiles'] for case in p['cases']]
        command = [sys.executable, '-m', 'pytest', *selectors, '-q', '--tb=short',
            '-o', 'junit_family=xunit1', f'--junitxml={directory / "pytest.xml"}',
            f'--basetemp={directory / "cases"}']
        (directory / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        with (directory / 'pytest.log').open('w') as log:
            try:
                return subprocess.run(command, cwd=self.root, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=600).returncode
            except subprocess.TimeoutExpired:
                log.write('\nAcceptance runner timed out after 600 seconds\n')
                return 124

    def report(self, xml_path, exit_code):
        errors, tests = [], []
        try:
            tests = list(ET.parse(xml_path).getroot().iter('testcase'))
        except (OSError, ET.ParseError) as error:
            errors.append(f'JUNIT_UNAVAILABLE: {type(error).__name__}')
        if exit_code != 0:
            errors.append(f'PYTEST_EXIT: {exit_code}')
        known = {self.case_key(case['test']) for p in self.manifest['profiles'] for case in p['cases']}
        observed = set()
        for test in tests:
            key = (test.get('classname'), test.get('name', '').split('[', 1)[0])
            identity = (test.get('classname'), test.get('name'))
            if key not in known:
                errors.append(f'UNEXPECTED_TEST: {identity}')
            if identity in observed:
                errors.append(f'DUPLICATE_TEST: {identity}')
            observed.add(identity)
        profiles = []
        for profile in self.manifest['profiles']:
            cases = []
            for case in profile['cases']:
                key = self.case_key(case['test'])
                matches = [test for test in tests if (test.get('classname'),
                    test.get('name', '').split('[', 1)[0]) == key]
                details = []
                for test in matches:
                    result = ('failed' if test.find('failure') is not None or test.find('error') is not None
                              else 'skipped' if test.find('skipped') is not None else 'passed')
                    details.append({'name': test.get('name'), 'checks': result,
                                    'seconds': test.get('time')})
                checks = ('passed' if len(matches) == case['expected_cases']
                          and all(d['checks'] == 'passed' for d in details) else 'failed')
                cases.append({'expected_outcome': case['outcome'], 'checks': checks,
                    'expected_cases': case['expected_cases'], 'observed_cases': len(matches),
                    'test': case['test'], 'details': details})
            profiles.append({'profile': profile['id'], 'checks': 'passed' if all(
                case['checks'] == 'passed' for case in cases) else 'failed', 'cases': cases})
        passed = not errors and all(p['checks'] == 'passed' for p in profiles)
        return {'schema': 'culsma_protocol_acceptance_v1', 'checks': 'passed' if passed else 'failed',
            'mode': 'simulation', 'profile_count': len(profiles),
            'outcome_cells': sum(len(p['cases']) for p in profiles), 'test_count': len(tests),
            'errors': errors, 'profiles': profiles}

    def run(self, directory):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        records = self.snapshot_inputs(directory)
        print(f'Protocol acceptance: {len(self.manifest["profiles"])} profiles; output {directory}', flush=True)
        exit_code = self.execute_tests(directory)
        summary = self.report(directory / 'pytest.xml', exit_code)
        summary['inputs'] = records
        summary['input_changes'] = self.input_changes(records)
        if (directory / 'inputs/manifest.json').read_bytes() != self.manifest_path.read_bytes():
            summary['input_changes'].append(str(self.manifest_path))
        if summary['input_changes']:
            summary['checks'] = 'failed'
            summary['errors'].append('ACCEPTANCE_INPUT_CHANGED')
        summary['completed_at'] = datetime.now(timezone.utc).isoformat()
        summary['artifacts'] = {'junit': 'pytest.xml', 'log': 'pytest.log', 'runs_and_stations': 'cases'}
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        return summary

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--output-dir', type=Path, required=True,
                            help='New directory; existing output is never overwritten')
        arguments = parser.parse_args()
        try:
            summary = cls().run(arguments.output_dir)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        for profile in summary['profiles']:
            print(profile['profile'] + ': ' + ', '.join(
                f'{case["expected_outcome"]}={case["checks"]} ({case["observed_cases"]}/{case["expected_cases"]})'
                for case in profile['cases']))
        print(f'{summary["checks"]}: {summary["test_count"]} tests; {arguments.output_dir / "summary.json"}')
        raise SystemExit(0 if summary['checks'] == 'passed' else 1)


if __name__ == '__main__':
    ProtocolAcceptanceSuite.main()
