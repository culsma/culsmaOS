import importlib.util
from pathlib import Path

import pytest

from tests.support.paths import ROOT

spec = importlib.util.spec_from_file_location('method_coverage', ROOT / 'tools/method_coverage.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestMethodCoverage:
    def document(self, covered=0, statements=10, branches=4, covered_branches=2, contexts=None):
        return {'files': {'src/culsma_os/material_system/interactors.py': {
            'executed_lines': [1],
            'functions': {'MaterialInteractor.reconcile': {
                'summary': {'num_statements': statements, 'covered_lines': covered,
                            'num_branches': branches, 'covered_branches': covered_branches},
                'executed_lines': [3] if covered else [],
                'contexts': contexts or {}, 'missing_lines': [3], 'missing_branches': [[3, 5]],
            }},
        }}}

    def test_importing_a_class_does_not_cover_its_method(self):
        result = module.MethodCoverageAudit().summarize(self.document())
        assert not result['methods'][0]['entry_observed']
        assert result['modules']['material_system']['unobserved'] == ['MaterialInteractor.reconcile']

    def test_lines_and_branches_are_reported_separately(self):
        row = module.MethodCoverageAudit().summarize(self.document(covered=8, contexts={'3': ['case|run']}))['methods'][0]
        assert row['statement_percent'] == 80 and row['branch_percent'] == 50
        assert row['observing_tests'] == ['case']

    def test_child_execution_is_not_given_an_invented_test_name(self):
        row = module.MethodCoverageAudit().summarize(self.document(covered=8))['methods'][0]
        assert row['entry_observed'] and row['unattributed_execution']
        assert row['observing_tests'] == []

    def test_interfaces_do_not_inflate_executable_coverage(self):
        document = self.document(covered=8)
        functions = next(iter(document['files'].values()))['functions']
        functions['MaterialRepository.commit'] = {'summary': {'num_statements': 0}}
        result = module.MethodCoverageAudit().summarize(document)
        assert len(result['methods']) == 1 and result['interface_declarations_excluded'] == 1

    @pytest.mark.parametrize('document', [{}, {'files': {}}])
    def test_missing_measurement_cannot_report_success(self, document):
        with pytest.raises(ValueError, match='METHOD_COVERAGE_DATA_REQUIRED'):
            module.MethodCoverageAudit().summarize(document)


    def test_method_attribution_excludes_other_methods_in_the_file(self):
        data = self.document(covered=8, contexts={'3': ['direct|run'], '20': ['other|run']})
        row = module.MethodCoverageAudit().summarize(data)['methods'][0]
        assert row['observing_tests'] == ['direct']


    def test_compact_data_uses_only_the_methods_observed_lines(self):
        from types import SimpleNamespace
        data = self.document(covered=8)
        source = SimpleNamespace(contexts_by_lineno=lambda path: {3: ['direct|run'], 20: ['other|run']})
        audit = module.MethodCoverageAudit()
        row = audit.summarize(audit.attach_contexts(data, source, ROOT))['methods'][0]
        assert row['observing_tests'] == ['direct']

    def test_parameter_pipes_remain_part_of_the_test_identity(self):
        data = self.document(covered=8, contexts={'3': ['case|parameter|run']})
        row = module.MethodCoverageAudit().summarize(data)['methods'][0]
        assert row['observing_tests'] == ['case|parameter']
