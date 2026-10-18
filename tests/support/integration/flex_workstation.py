"""Joint Flex processing and transport, one sequential program and station."""

import json
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


SOURCE = """// Engineering acceptance: condition a bead suspension and collect its liquid phase.
// Not a validated immunoprecipitation assay or a replacement for Module05.
let prep_plate=plate(label="Preparation",format="96well",capacity=200uL);
let prep=prep_plate[A1];
let magnetic_plate=plate(label="Magnetic",format="96well",capacity=2000uL);
let sample=magnetic_plate[A1];
let stock=tube(label="Stock",capacity=2000uL,load=[content(kind=particulate,type=beads,code="BEADS",attrs={bead_property:magnetic}):10uL,content(kind=formulation,type=buffer,code="BUFFER"):80uL]);
let collection=tube(label="Collection",capacity=2000uL);
prep << [stock];
agit(sample=prep[0],mode=shake,motion=orbital,rate=500rpm,duration=1s);
with env(thermal=37C,duration=1s) { hold(sample=prep); }
sample << [prep[0]];
with env(field=magnetic_rack) {
 hold(sample=sample);
 sep(sample=sample[0],program=magnetic_program(duration=5s));
 collection << [sample[0].contents[1]:40uL];
}
return collection;
"""


class FlexWorkstationFixture:
    def build(self, directory, change=None):
        f=TransferMatrixFixture(); plan=f.compile(SOURCE,directory)
        steps=[s for p in plan.plans for s in p.steps]
        def configure(raw):
            raw.update(robot_type='Flex',pipette='flex_1channel_1000',mount='left',
                tiprack={'load_name':'opentrons_flex_96_tiprack_1000ul','slot':'D3'},
                modules={
                    'shaker':{'model':'heaterShakerModuleV1','slot':'C1','adapter':'opentrons_96_flat_bottom_adapter'},
                    'heater':{'model':'temperature module gen2','slot':'B1'},
                    'magnet':{'model':'magneticBlockV1','slot':'C3','aspirate_height_mm':2,'release_destination':'D2'}},
                labware={'assay':{'load_name':'nest_96_wellplate_200ul_flat','slot':'D1'},
                         'captured':{'load_name':'nest_96_wellplate_2ml_deep','slot':'D2'},
                         'tubes':{'load_name':'opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap','slot':'B2'}})
            raw['bindings']={};tube=well=0
            for step in (s for s in steps if s.op=='AllocContainer'):
                if 'carrier_position' in step.args:
                    address={'labware':('assay','captured')[well],'well':'A1'};well+=1
                else:
                    tube+=1;address={'labware':'tubes','well':f'A{tube}'}
                raw['bindings'][step.step_id]=address
            transfers=[s for s in steps if s.op=='Mutation']
            assert len(transfers)==3
            raw['labware_moves']={
                next(s.step_id for s in steps if s.op=='agit'):[{'labware':'assay','destination':'module:shaker'}],
                next(s.step_id for s in steps if s.op=='env_hold'):[{'labware':'assay','destination':'module:heater'}],
                transfers[1].step_id:[{'labware':'assay','destination':'D1'}],
                next(s.step_id for s in steps if s.op=='sep'):[{'labware':'captured','destination':'module:magnet'}]}
            if change:change(raw,plan)
        context=f.context(directory,plan,config_mutation=configure)
        return plan,context,OSApplicationFactory().build(context)

    def assert_completed(self, app, plan, result):
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        baseline=run(plan,StubDriver(),init_state(plan))
        assert baseline.ok
        assert result.state.artifacts['material_state']==baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs']==baseline.state.artifacts['protocol_outputs']
        identity=result.user_result['os']['run_id']
        session=app.host.gateway.port.session
        assert session.motion.state['revision']>=5
        assert session.motion.positions()['assay']=='D1'
        assert session.motion.positions()['captured']=='D2'
        assert not session.magnetic.held
        assert not session.backend.module_access.active
        assert not session.backend.temperature_access.active
        assert app.client.lifecycle.reservations.get(identity).status=='released'
        assert not app.client.lifecycle.operations.resource.occupied()
        assert not app.client.lifecycle.operations.motions.motion.repository.pending('opentrons')
        return identity


class WorkstationDeviceFault:
    def __init__(self, original, hit, after):
        self.original,self.hit,self.after=original,hit,after
        self.calls=0

    def __call__(self,*args,**kwargs):
        self.calls+=1
        if self.calls==self.hit:
            if self.after:self.original(*args,**kwargs)
            raise TimeoutError('joint workstation completion unknown')
        return self.original(*args,**kwargs)
