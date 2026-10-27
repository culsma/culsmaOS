import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(shutil.which('node') is None,reason='Optional Node presentation checks')
def test_generic_track_and_slot_layouts_use_only_the_supplied_descriptor():
    script="""
import assert from 'node:assert/strict';
import {WorkstationLayoutView as V} from './src/culsma_os/console/web/workstation-layout.js';
const layout={definition:{schema:'culsma_layout_v1',selector_path:['deck'],variants:{X:{width:3,height:2,
 positions:[{id:'A1',x:0,y:0},{id:'A2',x:1,y:0}]}},collections:[
 {id:'modules',path:['modules'],keyed:true,model_field:'model',position_field:'slot',category:'module'},
 {id:'plates',path:['plates'],keyed:true,model_field:'model',position_field:'slot',parent_field:'module',category:'labware'}],
 catalogue:[{id:'wide',footprints:{A1:['A1','A2']}}]},
 configuration:{deck:'X',modules:{heater:{model:'wide',slot:'A1'}},plates:{sample:{model:'plate',module:'heater'}}}};
const before=structuredClone(layout),rows=V.entries(layout),slots=V.slots(layout,rows);
assert.equal(rows.find(row=>row.id==='sample').site,'A1');
assert.deepEqual(slots.positions[0].items.map(row=>row.id),['heater','sample']);
assert.deepEqual(slots.positions[1].items.map(row=>row.id),['heater']);
assert.deepEqual(layout,before);
assert.deepEqual(V.entries({definition:{schema:'culsma_layout_instances_v1',objects:[{id:'native'}]},configuration:{}}),[{id:'native'}]);
layout.definition.variants.X.positions[0].x=-1;assert.equal(V.slots(layout,rows),null);
"""
    result=subprocess.run([shutil.which('node'),'--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
