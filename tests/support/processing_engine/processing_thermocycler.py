"""Same OS thermal capability with a second official instrument implementation."""

from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.processing_engine.processing_thermal import ThermalFixture, DECLARATIONS, SOURCE
from culsma_os.processing_engine.interactors.material_volume import ProcessingMaterialVolumeInteractor
from culsma_os.driver_framework.models import OperationPreparationRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


SCALAR_SOURCE = SOURCE.replace('hold(sample=w[0])', 'hold(w[0])')


HOLDS = ' '.join(f'with env(thermal={temperature}C,duration={seconds}s) {{ hold(w[0]); }}'
                 for temperature, seconds in [(95, 1), (60, 2), (72, 3)])


CYCLE_SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + HOLDS + ' stock << [w[0]:20uL];'


class ThermocyclerFixture(ThermalFixture):
    def build(self, directory, source=SCALAR_SOURCE, configure=None):
        def configuration(raw):
            raw['modules'] = {'cycler': {'model': 'thermocyclerModuleV2', 'slot': '7'}}
            raw['labware']['assay'] = {'load_name': 'nest_96_wellplate_100ul_pcr_full_skirt', 'module': 'cycler'}
            if configure:
                configure(raw)
        return super().build(directory, source, configuration)
