"""Pure presentation of frozen run positions; no browser or device dependency."""
import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(shutil.which('node') is None, reason='Optional client checks require Node.js')
def test_loading_layout_groups_frozen_materials_supplies_and_explicit_well_geometry():
    script = """
import assert from 'node:assert/strict';
import {RunSetupLayout as Layout} from './src/culsma_os/console/web/setup-layout.js';
const placement=(site,track='3',carrier='reagents')=>({carrier,track,site});
const plan={items:[{kind:'well',address:{labware:'plate',well:'A1'},geometry:[8,12]}],
 loadout:[{labware:'standard',placement:placement('1'),containers:[{name:'__user_named_stock',well:'1',volume_uL:1000}]},
 {labware:'diluent',placement:placement('2'),containers:[{name:'diluent',well:'1',volume_uL:1000}]},
 {labware:'plate',placement:placement('1','6','plates'),containers:[{name:'lowered_well',well:'A1',volume_uL:0},{well:'A3',volume_uL:0}]}],
 supplies:[{id:'tips',model:'tip-model',carrier:'tip_carrier',track:'12',site:'1',available:12,positions:['1','2']}]};
const before=JSON.stringify(plan),items=Layout.items(plan),groups=Layout.groups(items);
assert.equal(items.length,4);assert.equal(groups.length,3);
assert.deepEqual(groups.map(g=>g.placement.track),['3','6','12']);
assert.deepEqual(groups[0].items.map(i=>i.id),['standard','diluent']);
assert.equal(Layout.label(plan,items[0]),'__user_named_stock');
assert.equal(Layout.label(plan,items[2]),'plate');
assert.equal(Layout.location(items[3]),'Carrier tip_carrier · track 12 · site 1');
const wells=Layout.wells(plan,items[2]);
assert.equal(wells.length,8);assert.equal(wells[0].length,12);
assert.equal(wells[0][0],'A1');assert.equal(wells[7][11],'H12');
assert.equal(Layout.wells(plan,items[0]),null);
assert.equal(JSON.stringify(plan),before);
// Missing or inconsistent geometry never fabricates a 96-well plate.
assert.equal(Layout.geometry({items:[]},items[2]),null);
assert.equal(Layout.geometry({items:plan.items,candidates:[{labware:'plate',geometry:[16,24]}]},items[2]),null);
assert.equal(Layout.wells(plan,{...items[2],containers:[{well:'97'}]}),null);
assert.equal(Layout.wells(plan,{...items[2],containers:[{well:'A13'}]}),null);
assert.equal(Layout.geometry({items:[{address:{labware:'plate'},geometry:[8,100000]}]},items[2]),null);
// Unplaced and slot-based records stay visible without inventing Hamilton tracks.
assert.equal(Layout.location({}), 'Placement not specified in this plan');
assert.equal(Layout.location({placement:{slot:'A1'}}),'slot A1');
assert.equal(Layout.groups([{id:'one'},{id:'two'}]).length,2);
assert.deepEqual(Layout.items({}),[]);
"""
    result=subprocess.run([shutil.which('node'),'--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_loading_layout_has_no_mutation_or_current_configuration_dependency():
    source=(ROOT/'src/culsma_os/console/web/setup-layout.js').read_text()
    assert not any(value in source for value in ('fetch(', 'configurationFetch(', 'localStorage', 'sessionStorage', 'innerHTML', 'Authorization', 'confirm_setup', 'submit_program'))
    assert "action:'setup.inspect-item'" in source and 'setupFingerprint = plan.fingerprint' in source
    setup=(ROOT/'src/culsma_os/console/web/setup.js').read_text()
    assert 'this.confirmations.delete(run.run_id)' in setup
    assert 'this.layout.render(plan,run)' in setup
