"""Summarize measured method execution; coverage is not proof of assertion quality."""
import argparse
from collections import defaultdict
import json
from pathlib import Path


class MethodCoverageAudit:
    def summarize(self, document):
        if not isinstance(document.get('files'), dict) or not document['files']:
            raise ValueError('METHOD_COVERAGE_DATA_REQUIRED')
        methods, interfaces = [], 0
        modules = defaultdict(lambda: {'methods': 0, 'observed': 0, 'unobserved': []})
        for path, data in sorted(document['files'].items()):
            parts = Path(path).parts
            if 'culsma_os' not in parts:
                continue
            position = parts.index('culsma_os')
            owner = parts[position + 1] if len(parts) > position + 2 else Path(path).stem
            for name, measurement in sorted(data.get('functions', {}).items()):
                if name.count('.') != 1:
                    continue
                counts = measurement['summary']
                statements = counts['num_statements']
                if not statements:
                    interfaces += 1
                    continue
                observed = counts['covered_lines'] > 0
                contexts = sorted({context.rsplit('|', 1)[0]
                                   for line in measurement.get('executed_lines', [])
                                   for context in (measurement.get('contexts') or data.get('contexts', {})).get(str(line), []) if context})
                row = {'path': path, 'method': name, 'owner': owner,
                       'entry_observed': observed, 'observing_tests': contexts,
                       'unattributed_execution': observed and not contexts,
                       'statement_percent': round(100 * counts['covered_lines'] / statements, 2),
                       'branch_percent': (round(100 * counts['covered_branches'] / counts['num_branches'], 2)
                                          if counts['num_branches'] else None),
                       'missing_lines': measurement.get('missing_lines', []),
                       'missing_branches': measurement.get('missing_branches', [])}
                methods.append(row)
                modules[owner]['methods'] += 1
                modules[owner]['observed'] += int(observed)
                if not observed:
                    modules[owner]['unobserved'].append(name)
        if not methods:
            raise ValueError('METHOD_COVERAGE_SCOPE_EMPTY')
        return {'schema': 'culsma_method_coverage_v1', 'methods': methods,
                'modules': dict(modules), 'interface_declarations_excluded': interfaces,
                'limits': ['Execution coverage does not prove assertion strength',
                           'Unattributed child-process execution needs a behavioral test reference',
                           'Do not count file/class definition execution as a method invocation']}

    def attach_contexts(self, document, coverage_data, root):
        for path, content in document['files'].items():
            content['contexts'] = {str(line): values for line, values in
                                   coverage_data.contexts_by_lineno(str((root / path).resolve())).items()}
        return document

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('coverage_json', type=Path)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--data-file', type=Path)
        args = parser.parse_args()
        audit = cls()
        document = json.loads(args.coverage_json.read_text())
        if args.data_file:
            from coverage import CoverageData
            data = CoverageData(basename=str(args.data_file.resolve()))
            data.read()
            audit.attach_contexts(document, data, Path.cwd())
        result = audit.summarize(document)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result['modules'], indent=2))


if __name__ == '__main__':
    MethodCoverageAudit.main()
