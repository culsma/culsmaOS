"""Deck rendering consumes frozen generic layout descriptors, without vendor tables."""
import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(shutil.which('node') is None,reason='Optional presentation checks require Node.js')
def test_frozen_deck_geometry_bounds_spans_sites_and_missing_metadata():
    script="""
import assert from 'node:assert/strict';
import {RunSetupDeck as Deck} from './src/culsma_os/console/web/setup-deck.js';
const make=(count,span,sites=5)=>({layout:{configuration:{deck:'declared',carriers:{rack:{model:'model',track:'3'}},labware:{plate:{carrier:'rack',site:'2',model:'plate'}}},definition:{
 schema:'culsma_layout_v1',selector_path:['deck'],variants:{declared:{label:'Declared test deck',presentation:'tracks',width:count,
 positions:Array.from({length:count},(_,i)=>({id:String(i+1),x:i,width:1}))}},
 collections:[{category:'carrier',keyed:true,path:['carriers'],model_field:'model',position_field:'track'},
 {category:'labware',keyed:true,path:['labware'],parent_field:'carrier',model_field:'model',position_field:'site'}],
 catalogue:[{id:'model',sites:Array.from({length:sites},(_,i)=>String(i+1)),footprints:{'3':Array.from({length:span},(_,i)=>String(i+3))}}]}}});
for(const count of [30,54]) for(const span of [1,2,4,5,6,7]) {
 const plan=make(count,span),before=JSON.stringify(plan),scene=Deck.scene(plan);
 assert.equal(scene.positions.length,count);assert.equal(scene.carriers[0].start,2);
 assert.equal(scene.carriers[0].span,span);assert.equal(scene.carriers[0].sites.length,5);
 assert.equal(scene.carriers[0].placements[0].id,'plate');assert.equal(JSON.stringify(plan),before);
}
assert.equal(Deck.scene({}),null);
const outside=make(4,6);assert.equal(Deck.scene(outside),null);
const overlap=make(54,6);overlap.layout.configuration.carriers.other={model:'model',track:'3'};assert.equal(Deck.scene(overlap),null);
const unknown=make(54,6);unknown.layout.configuration.carriers.rack.model='unknown';assert.equal(Deck.scene(unknown),null);
const badsite=make(54,6);badsite.layout.configuration.labware.plate.site='6';assert.equal(Deck.scene(badsite),null);
const duplicate=make(54,6);duplicate.layout.configuration.labware.other={...duplicate.layout.configuration.labware.plate};assert.equal(Deck.scene(duplicate),null);
const oversized=make(54,6);oversized.layout.definition.variants.declared.width=100000;assert.equal(Deck.scene(oversized),null);
"""
    result=subprocess.run([shutil.which('node'),'--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_deck_presentation_has_no_hamilton_geometry_or_current_configuration_lookup():
    source=(ROOT/'src/culsma_os/console/web/setup-deck.js').read_text()
    assert not any(value in source for value in ['fetch(', 'configurationFetch(', 'localStorage', 'innerHTML', 'STAR-54', 'CAR_5DWP'])
    assert 'plan.layout' in source and "action:'setup.inspect-deck-item'" in source
