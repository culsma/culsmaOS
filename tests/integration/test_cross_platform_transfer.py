from importlib.util import find_spec
import pytest
from tests.acceptance.cross_platform_transfer import CrossPlatformTransferAcceptance


class TestCrossPlatformTransfer:
    def require_backends(self):
        for package in ('culsma_opentrons', 'opentrons', 'culsma_pylabrobot', 'pylabrobot'):
            if find_spec(package) is None:
                pytest.skip('Install both external simulator plugins for paired acceptance')

    @pytest.mark.parametrize('name', [
        'continuous-transfer', 'unequal-eight-wells', 'layout-splitting',
        'below-p300-minimum', 'first-dispense-fails', 'second-dispense-fails',
        'second-group-batch-fails',
    ])
    def test_same_program_two_backends(self, tmp_path, name):
        self.require_backends()
        campaign = CrossPlatformTransferAcceptance()
        scenario = next(s for s in campaign.manifest['scenarios'] if s['name'] == name)
        result = campaign.run_scenario(scenario, tmp_path / name)
        assert result['checks'] == 'passed'

    def test_same_program_language_cli(self, tmp_path):
        self.require_backends()
        assert CrossPlatformTransferAcceptance().cli_pair(tmp_path)['checks'] == 'passed'

