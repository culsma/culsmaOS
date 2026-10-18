"""Flex passive field closes through the ordinary journaled motion path."""

import json
from dataclasses import replace
import pytest
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
from tests.support.processing_engine.processing_magnetic import MagneticFixture, SOURCE


class BlockFixture:
    def build(self, directory, source=SOURCE, change=None):
        f=TransferMatrixFixture(); plan=f.compile(source,directory)
        def configure(raw):
            raw.update(robot_type='Flex',pipette='flex_1channel_1000',mount='left',
                tiprack={'load_name':'opentrons_flex_96_tiprack_1000ul','slot':'D3'},
                modules={'magnet':{'model':'magneticBlockV1','slot':'C1','aspirate_height_mm':2,'release_destination':'D1'}},
                labware={'assay':{'load_name':'nest_96_wellplate_2ml_deep','slot':'D1'},
                         'tubes':{'load_name':'opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap','slot':'B1'}})
            raw['bindings']={};tube=0
            for s in (s for p in plan.plans for s in p.steps if s.op=='AllocContainer'):
                if 'carrier_position' in s.args:address={'labware':'assay','well':s.args['carrier_position']['value']}
                else:
                    tube+=1;address={'labware':'tubes','well':f'A{tube}'}
                raw['bindings'][s.step_id]=address
            sep=next(s for p in plan.plans for s in p.steps if s.op=='sep')
            raw['labware_moves']={sep.step_id:[{'labware':'assay','destination':'module:magnet'}]}
            if change:change(raw,plan)
        context=f.context(directory,plan,config_mutation=configure)
        return plan,context,OSApplicationFactory().build(context)
