"""Eight-channel shared physical effects through the hosted language path."""

from dataclasses import replace
import ast
from pathlib import Path
import sqlite3
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.material_system.models import MaterialCommitProposal
from culsma_os.material_system.repositories.local import LocalMaterialRepository
from tests.support.transfer_engine.plate96 import PlateFixture, BUFFER
from tests.support.transfer_engine.group_handoff import GroupFixture


SOURCE=f'let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:1000uL]); let assay=plate(label="Assay",format="96well",capacity=200uL); assay[A1:H1] << [stock:20uL];'


class MultichannelOSFixture:
    def build(self, tmp_path, source=SOURCE, pipette='p20_multi_gen2', reservoir=True):
        fixture=PlateFixture();plan=fixture.compile(source,tmp_path)
        def configure(raw):
            raw['tiprack']['load_name']='opentrons_96_tiprack_20ul' if pipette.startswith('p20') else 'opentrons_96_tiprack_300ul'
            if reservoir: raw['labware']['tubes']['load_name']='nest_12_reservoir_15ml'
        context=fixture.context(tmp_path,plan,pipette,config_mutation=configure)
        return plan,context,OSApplicationFactory().build(context)
