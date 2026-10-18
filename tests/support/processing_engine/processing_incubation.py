"""Incubate is a language workflow; heater execution is a selected instrument capability."""

import ast
import json
from pathlib import Path
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.processing_engine.processing_agitation import AgitationFixture, DECLARATIONS, SHAKE
from tests.support.processing_engine.processing_thermal import ThermalFixture
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


INCUBATE = 'Incubate(sample=w[0],temp=37C,duration=30s);'


SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + INCUBATE + ' ' + SHAKE + ' stock << [w[0]:20uL];'


HOLD_SOURCE = DECLARATIONS + ' w << [stock:50uL]; ' + INCUBATE + ' stock << [w[0]:20uL];'
