"""Concurrent file reads cannot replace a newer selection or submit a run."""
import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(shutil.which('node') is None, reason='Optional Node presentation checks')
def test_file_selection_and_open_ignore_out_of_order_reads():
    script = """
import assert from 'node:assert/strict';
import {ConsolePrograms} from './src/culsma_os/console/web/programs.js';
globalThis.sessionStorage={getItem:()=>null};
const app={syncBusy(){},showAlert(){},interaction:{result(){},responseOutcome(){return 'invalid';}},
 activation:{view:{active:{fingerprint:'a',origin:{draft_id:'draft'}}},async refresh(){}}};
const programs=new ConsolePrograms(app);programs.render=()=>{};
const requests=[];programs.request=body=>new Promise(resolve=>requests.push({body,resolve}));
const first=programs.inspect('old.culs',false);
const second=programs.inspect('project/new.culs',false);
assert.equal(requests.length,2);
requests[1].resolve({valid:true,program_id:'project/new.culs'});await second;
requests[0].resolve({valid:false,program_id:'old.culs'});await first;
assert.equal(programs.selection,'project/new.culs');assert.equal(programs.inspection.program_id,'project/new.culs');
assert.equal(programs.opened,false);assert.equal(programs.working,false);
// A double click may open while the first click's source read is still pending.
const click=programs.inspect('project/new.culs',false);
const open=programs.inspect('project/new.culs',true);
await Promise.resolve();await Promise.resolve();
assert.equal(requests.at(-1).body.action,'preview');
requests.at(-1).resolve({valid:true,program_id:'project/new.culs',preparation:{configuration_fingerprint:'a'}});await open;
requests[2].resolve({valid:true,program_id:'project/new.culs',source:'older read'});await click;
assert.equal(programs.opened,true);assert.ok(programs.inspection.preparation);
assert.equal(programs.reviewedConfiguration.fingerprint,'a');assert.equal(programs.working,false);
assert.ok(requests.every(item=>['inspect','preview'].includes(item.body.action)));
"""
    result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script],
                            cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which('node') is None, reason='Optional Node presentation checks')
def test_direct_launch_collapses_duplicate_gestures_and_stops_failed_checks():
    script = """
import assert from 'node:assert/strict';
import {ConsolePrograms} from './src/culsma_os/console/web/programs.js';
globalThis.sessionStorage={getItem:()=>null};
const programs=new ConsolePrograms({});programs.render=()=>{};programs.mountFiles=()=>{};
let submitted=0,release;
programs.inspect=async id=>{programs.selection=id;programs.inspection={valid:true,preparation:{status:'available'}};};
programs.submit=()=>{submitted++;return new Promise(resolve=>release=resolve);};
const first=programs.launch('transfer.culs');await Promise.resolve();
await programs.launch('transfer.culs');assert.equal(submitted,1);
release();await first;assert.equal(programs.launching,false);
programs.inspect=async id=>{programs.selection=id;programs.inspection={valid:true,preparation:{status:'blocked'}};};
await programs.launch('transfer.culs');assert.equal(submitted,1);
programs.inspect=async id=>{programs.selection=id;programs.inspection=null;};
await programs.launch('transfer.culs');assert.equal(submitted,1);
"""
    result=subprocess.run([shutil.which('node'),'--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
