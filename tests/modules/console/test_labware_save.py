"""The console saves once, observes receipts and never repeats unknown mutations."""
import os
import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(not (os.environ.get('CULSMA_OS_NODE') or shutil.which('node')),reason='Node presentation checks')
def test_single_save_rejection_and_receipt_state_machine():
    script=r"""
import assert from 'node:assert/strict';
import {ConsoleLabware} from './src/culsma_os/console/web/labware.js';
import {ConsoleActivation} from './src/culsma_os/console/web/activation.js';
function fixture(kind='accepted') {
 const calls=[],results=[],app={activation:{value:null,pending(){return this.value},remember(v){this.value=v},async refresh(){}},
  interaction:{result(...v){results.push(v)}},refresh(){},async configurationFetch(path,value){
   calls.push(value);
   if(value.action==='prepare') {
    if(kind==='invalid')throw Object.assign(new Error('INVALID_POSITION'),{httpStatus:409});
    return {draft:{draft_id:'draft',revision:1},expected_fingerprint:'fp',impact:[]};
   }
   if(kind==='lost')throw new Error('response lost');
   return {status:'accepted'};
  }};
 const editor=new ConsoleLabware(app);editor.update=()=>{};
 editor.catalogue={targets:[{id:'rack/1',occupants:['tip']} ]};editor.target='rack/1';
 editor.category='empty';editor.envelope={editing_ready:true,configuration_fingerprint:'fp'};editor.open=true;
 return {editor,app,calls,results};
}
let f=fixture();
await Promise.all([f.editor.save(),f.editor.save()]);
assert.deepEqual(f.calls.map(c=>c.action),['prepare','apply']);
const request=f.editor.pending.request_id;
assert.equal(f.editor.open,true);assert.equal(f.editor.saving,true);
f.editor.observeActivation({receipt:{request_id:'other',status:'applied'}});assert.equal(f.editor.open,true);
f.editor.observeActivation({receipt:{request_id:request,status:'starting'}});assert.equal(f.editor.open,true);
f.editor.observeActivation({active:{fingerprint:'new-fp'},receipt:{request_id:request,status:'applied'}});
assert.equal(f.editor.open,true);
f.editor.envelope.configuration_fingerprint='new-fp';f.editor.envelope.editing_ready=false;f.editor.completeSave();
assert.equal(f.editor.open,true);
f.editor.envelope.editing_ready=true;f.editor.completeSave();
assert.equal(f.editor.open,false);assert.equal(f.results[0][1],'succeeded');
f=fixture('invalid');await f.editor.save();assert.deepEqual(f.calls.map(c=>c.action),['prepare']);
assert.equal(f.editor.category,'empty');assert.equal(f.editor.open,true);assert.equal(f.editor.busy,false);
f=fixture('lost');await f.editor.save();await f.editor.save();
assert.deepEqual(f.calls.map(c=>c.action),['prepare','apply']);
assert.ok(f.editor.pending);assert.equal(f.editor.open,true);assert.equal(f.editor.saving,false);
f.editor.observeActivation({receipt:{request_id:f.editor.pending.request_id,status:'failed',error:'BUILD_FAILED'}});
assert.equal(f.editor.open,true);assert.equal(f.editor.pending,null);assert.match(f.editor.error,/BUILD_FAILED/);
// Reverse response order: an older read cannot clear a newer save or replace its receipt.
const storage=new Map();globalThis.sessionStorage={getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
const reads=[],notices=[],activation=new ConsoleActivation({configurationFetch:()=>new Promise(resolve=>reads.push(resolve)),interaction:{result:(...v)=>notices.push(v)}});
activation.remember({request_id:'first'});const firstRead=activation.refresh();
activation.remember({request_id:'second'});const secondRead=activation.refresh();
reads[1]({receipt:{request_id:'second',status:'applied'},active:{fingerprint:'second'}});await secondRead;
reads[0]({receipt:{request_id:'first',status:'applied'},active:{fingerprint:'first'}});await firstRead;
assert.equal(activation.view.active.fingerprint,'second');assert.equal(notices.length,1);assert.equal(activation.pending(),null);

"""
    result=subprocess.run([os.environ.get('CULSMA_OS_NODE') or shutil.which('node'),'--input-type=module','-e',script],
        cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
