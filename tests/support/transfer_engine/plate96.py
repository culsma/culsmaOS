"""96-well execution preserves language well identity through the official simulator."""

from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import pytest
from culsma.runtime.material.args import arg_string
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma.driver.stub import StubDriver
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext, RunRequest
from culsma_os.transfer_engine.models import TransferRequest
from culsma_os.workspace_manager.repository import SqliteSpaceRepository
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER


class PlateFixture(TransferMatrixFixture):
    source_text = f'''
let stock = tube(label="Stock",capacity=2000uL,load=[{BUFFER}:200uL]);
let assay = plate(label="Assay",format="96well",carrier_id="PlateA",capacity=200uL);
let wells = assay[A1:B2];
wells[0] << [stock:50uL];
wells[3] << [stock:20uL];
wells[1] << [wells[0]:20uL];
stock << [wells[1]:20uL];
'''

    def context(self, directory, plan, pipette='p300_single_gen2', policy='single', config_mutation=None):
        allocations = [s for p in plan.plans for s in p.steps if s.op=='AllocContainer']
        bindings = {}
        carriers = {}
        tubes = 0
        for step in allocations:
            if arg_string(step.args.get('kind'))=='well':
                carrier = arg_string(step.args.get('carrier_id'))
                if carrier not in carriers:
                    carriers[carrier] = f'plate{len(carriers)+1}'
                bindings[step.step_id]={'labware':carriers[carrier],'well':arg_string(step.args.get('carrier_position'))}
            else:
                bindings[step.step_id]={'labware':'tubes','well':f'A{tubes+1}'}
                tubes+=1
        config={
            'robot_type':'OT-2','api_level':'2.20','pipette':pipette,'mount':'right',
            'tiprack':{'load_name':'opentrons_96_tiprack_20ul' if pipette=='p20_single_gen2' else 'opentrons_96_tiprack_300ul','slot':'2'},
            'labware':{'tubes':{'load_name':'opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap','slot':'1'}, **{name:{'load_name':'corning_96_wellplate_360ul_flat','slot':str(i+3)} for i,name in enumerate(carriers.values())}},
            'bindings':bindings,'transfer_policy':{'stroke_mode':policy},
        }
        if config_mutation:
            config_mutation(config)
        path=directory/'deck.json';path.write_text(json.dumps(config))
        return HostBuildContext(directory/'os.sqlite3','opentrons-simulator',path,directory/'artifacts')

    def run_case(self, directory, source, pipette='p300_single_gen2'):
        plan=self.compile(source,directory)
        context=self.context(directory,plan,pipette)
        app=OSApplicationFactory().build(context)
        return plan,context,app

    def assert_material(self, result, expected):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        containers=result.state.artifacts['material_state']['containers']
        volumes={c['metadata'].get('label'):c['volume_uL'] for c in containers.values()}
        assert volumes==pytest.approx(expected)
