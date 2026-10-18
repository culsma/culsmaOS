from tests.support.paths import ROOT
from pathlib import Path
import importlib.metadata
import json
import subprocess
import sys
import pytest
from culsma import cli
from culsma_os.bootstrap import OSApplicationFactory, LanguageProgramExecutorFactory
from culsma.driver.models import ProgramExecutionRequest


SOURCE = ROOT / "examples/transfer/transfer.culs"


DECK = ROOT / "examples/transfer/deck.json"
