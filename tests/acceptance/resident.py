"""Reproducible gate for resident full protocols, program workspaces and recovery."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


class ResidentAcceptanceSuite:
    def __init__(self, root=None, manifest=None):
        self.root = Path(root or Path(__file__).resolve().parents[2]).resolve()
        self.path = Path(manifest or self.root/'tests/acceptance/manifests/resident.json')
        self.manifest_bytes = self.path.read_bytes()
        self.manifest = json.loads(self.manifest_bytes)
        self.validate()

    def source(self, relative):
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError('ACCEPTANCE_INPUT_INVALID')
        path = (self.root/relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError('ACCEPTANCE_INPUT_INVALID')
        return path

    def validate(self):
        if self.manifest.get('schema') != 'culsma_resident_acceptance_suite_v1':
            raise ValueError('ACCEPTANCE_SCHEMA_UNSUPPORTED')
        groups = self.manifest.get('groups')
        if not isinstance(groups, list) or not groups:
            raise ValueError('ACCEPTANCE_GROUPS_REQUIRED')
        selectors = set()
        for group in groups:
            selector = group.get('selector', '')
            if not isinstance(selector, str):
                raise ValueError('ACCEPTANCE_SELECTOR_INVALID')
            parts = selector.split('::')
            if (len(parts) != 2 or not parts[0].startswith('tests/') or not parts[0].endswith('.py')
                    or not parts[1].isidentifier() or selector in selectors):
                raise ValueError('ACCEPTANCE_SELECTOR_INVALID')
            self.source(parts[0]); selectors.add(selector)
            names = group.get('expected_tests')
            if (not isinstance(names, list) or not names or any(not isinstance(n, str)
                    or not n.startswith('test_') for n in names) or len(names) != len(set(names))):
                raise ValueError('ACCEPTANCE_TEST_NAMES_INVALID')
        inputs = self.manifest.get('inputs')
        if not isinstance(inputs, list) or not inputs:
            raise ValueError('ACCEPTANCE_INPUTS_REQUIRED')
        for relative in inputs: self.source(relative)
        count = self.manifest.get('expected_audit_bundles')
        if type(count) is not int or count < 1:
            raise ValueError('ACCEPTANCE_AUDIT_COUNT_INVALID')

    def expected(self):
        return {(group['selector'].split('::')[0].removesuffix('.py').replace('/', '.')
                 + '.' + group['selector'].split('::')[1], name)
                for group in self.manifest['groups'] for name in group['expected_tests']}

    def report(self, path, exit_code):
        errors, tests, seen = [], [], set()
        try:
            tests = list(ET.parse(path).getroot().iter('testcase'))
        except (OSError, ET.ParseError): errors.append('ACCEPTANCE_JUNIT_UNAVAILABLE')
        for case in tests:
            key = case.get('classname'), case.get('name')
            if key in seen: errors.append(f'ACCEPTANCE_DUPLICATE: {key}')
            seen.add(key)
            if any(case.find(kind) is not None for kind in ('failure', 'error', 'skipped')):
                errors.append(f'ACCEPTANCE_CASE_FAILED: {key}')
        if exit_code != 0: errors.append(f'ACCEPTANCE_EXIT: {exit_code}')
        if seen != self.expected(): errors.append('ACCEPTANCE_TEST_SET_MISMATCH')
        return {'schema':'culsma_resident_acceptance_v1','checks':'failed' if errors else 'passed',
                'mode':'official_simulation','test_count':len(tests),'errors':errors,
                'cases':[{'class':c.get('classname'),'name':c.get('name'),'seconds':c.get('time')}
                         for c in tests]}

    def input_changes(self, inputs):
        changes = []
        for item in inputs:
            try:
                matches = sha256(self.source(item['path']).read_bytes()).hexdigest() == item['sha256']
            except (OSError, ValueError):
                matches = False
            if not matches: changes.append(item['path'])
        return changes

    def execute(self, output):
        command = [sys.executable,'-m','pytest',*(g['selector'] for g in self.manifest['groups']),
            '-q','--tb=short','-o','junit_family=xunit1',f'--junitxml={output/"pytest.xml"}',
            f'--basetemp={output/"cases"}']
        (output/'command.json').write_text(json.dumps(command,indent=2)+'\n')
        with (output/'pytest.log').open('w') as log:
            try: return subprocess.run(command,cwd=self.root,stdout=log,stderr=subprocess.STDOUT,timeout=1200).returncode
            except subprocess.TimeoutExpired:
                log.write('\nAcceptance exceeded 1200 seconds\n')
                return 124

    def run(self, directory):
        output = Path(directory).resolve(); output.mkdir(parents=True,exist_ok=False)
        sources = set(self.manifest['inputs'])
        sources.update(g['selector'].split('::')[0] for g in self.manifest['groups'])
        sources.update(str(p.relative_to(self.root)) for p in (self.root/'src').rglob('*.py'))
        sources.update(str(p.relative_to(self.root)) for p in (self.root/'tests/support').rglob('*.py'))
        if (self.root/'tests/conftest.py').is_file(): sources.add('tests/conftest.py')
        inputs = []
        for relative in sorted(sources):
            content = self.source(relative).read_bytes(); target = output/'inputs'/relative
            target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(content)
            inputs.append({'path':relative,'sha256':sha256(content).hexdigest()})
        (output/'manifest.json').write_bytes(self.manifest_bytes)
        print(f'Resident acceptance: {len(self.expected())} cases; {output}',flush=True)
        code = self.execute(output); report = self.report(output/'pytest.xml',code)
        changed = self.input_changes(inputs)
        try: manifest_matches = self.path.read_bytes() == self.manifest_bytes
        except OSError: manifest_matches = False
        if not manifest_matches: changed.append('manifest')
        audits = sorted([*output.glob('cases/**/resident-protocol-audit.json'),
                         *output.glob('cases/**/audit-before-restart.json'),
                         *output.glob('cases/**/resident-cli-audit.json')])
        for audit in audits:
            try:
                data = json.loads(audit.read_text())
                valid = isinstance(data.get('scenario'), str) and isinstance(data.get('runs'), list) and bool(data['runs']) and isinstance(data.get('station'), dict)
            except (OSError, ValueError, AttributeError): valid = False
            if not valid: report['errors'].append('ACCEPTANCE_AUDIT_INVALID')
        if changed: report['errors'].append('ACCEPTANCE_INPUT_CHANGED')
        if len(audits) != self.manifest['expected_audit_bundles']:
            report['errors'].append('ACCEPTANCE_AUDITS_INCOMPLETE')
        report.update(inputs=inputs,input_changes=changed,audits=[str(p.relative_to(output)) for p in audits])
        report['checks'] = 'failed' if report['errors'] else 'passed'
        (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        return report

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--output-dir',type=Path,required=True)
        args = parser.parse_args()
        report = cls().run(args.output_dir)
        print(f"{report['checks']}: {report['test_count']} cases; {len(report['audits'])} audit bundles",flush=True)
        raise SystemExit(0 if report['checks'] == 'passed' else 1)


if __name__ == '__main__':
    ResidentAcceptanceSuite.main()
