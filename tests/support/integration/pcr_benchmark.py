"""Purposeful full-length PCR acceptance, including original qualitative constraints."""

from tests.support.paths import ROOT
from pathlib import Path
import hashlib
import json
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


EXAMPLE = ROOT / 'examples/pcr-benchmark'


class PCRFixture:
    def build(self, directory, original=False, change=None, configure=None):
        source = (EXAMPLE / ('protocol.original.culs' if original else 'protocol.culs')).read_text()
        if change: source = change(source)
        plan = TransferMatrixFixture().compile(source, directory)
        raw = json.loads((EXAMPLE / 'deck.json').read_text())
        if configure: configure(raw)
        path = directory / 'deck.json'; path.write_text(json.dumps(raw))
        context = HostBuildContext(directory / 'os.sqlite3', 'opentrons-simulator', path, directory / 'artifacts')
        return plan, context, OSApplicationFactory().build(context)

    def schedule(self):
        return [(98,30)] + [(98,10),(60,20),(72,30)] * 30 + [(72,300)]
