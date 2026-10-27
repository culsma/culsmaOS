"""Navigation and run-stage selection are pure presentation, never execution."""
import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(shutil.which('node') is None, reason='Optional Node presentation checks')
def test_navigation_keeps_existing_routes_and_separates_active_history_and_stages():
    script = """
import assert from 'node:assert/strict';
import {ConsoleNavigation as N} from './src/culsma_os/console/web/navigation.js';
for(const [hash,page] of [['#station','station'],['#configuration','configuration'],['#programs','programs'],
 ['#runs','runs'],['#system','system'],['#workstation-state','station'],['#history','runs'],['#system/runtime','system']])
 assert.equal(N.resolve(hash).page,page);
assert.deepEqual(N.resolve('#run/test-run/results'),{page:'run',section:'results',runId:'test-run',group:'Workstation'});
assert.equal(N.resolve('#run/test-run').section,null);
assert.equal(N.resolve('').page,'station');
assert.equal(N.phase({status:'awaiting_setup'}),'preparation');
assert.equal(N.phase({status:'running'}),'execution');
assert.equal(N.phase({status:'needs_reconciliation'}),'execution');
assert.equal(N.phase({status:'completed'}),'results');
assert.equal(N.phase({status:'completed'},'preparation'),'preparation');
assert.deepEqual(N.groups.map(g=>g.label),['Workstation','System Settings','System Info']);
assert.equal(N.resolve('#configuration').group,'System Settings');
assert.equal(N.resolve('#programs').group,'Workstation');
const records=[{run_id:'active',status:'running'},{run_id:'unknown',status:'needs_reconciliation'},
 {run_id:'done',status:'completed'},{run_id:'failed',status:'failed'},{run_id:'cancelled',status:'cancelled'}];
const before=JSON.stringify(records);
assert.deepEqual(N.runs(records).map(r=>r.run_id),['active','unknown']);
assert.deepEqual(N.runs(records,true).map(r=>r.run_id),['done','failed','cancelled']);
assert.equal(JSON.stringify(records),before);
"""
    result=subprocess.run([shutil.which('node'),'--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
