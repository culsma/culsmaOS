import json
import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


def test_reviewed_revision_is_not_confused_with_applied_configuration():
    node=shutil.which('node')
    if not node:pytest.skip('Node is an optional UI contract test dependency')
    source=(ROOT/'src/culsma_os/console/web/programs.js').read_text()
    code="""
const module=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
const origin={draft_id:'draft',revision:2,configuration_fingerprint:'fingerprint'};
const controller=new module.ConsolePrograms({activation:{view:{active:{origin}}}});
const report={draft_id:'draft',revision:2,fingerprint:'fingerprint'};
if (!controller.bindingIsActive(report)) throw Error('Exact saved revision should match');
for (const change of [{revision:1},{fingerprint:'other'},{draft_id:'different'}]) {
 if (controller.bindingIsActive({...report,...change})) throw Error('Mismatched revision marked active');
}
""".replace('SOURCE',json.dumps(source),1)
    result=subprocess.run([node,'--input-type=module','-e',code],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
