"""Pure client-contract checks; no browser, build system or runtime Node dependency."""
import shutil
import subprocess
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(shutil.which('node') is None, reason='Optional client checks require Node.js')
def test_write_response_uncertainty_and_field_identity():
    script = """
import assert from 'node:assert/strict';
import {ConsoleInteraction} from './src/culsma_os/console/web/interaction.js';
const view = new ConsoleInteraction(null,null);
// A server error or lost response is not proof that a write was rejected.
assert.equal(view.responseOutcome({httpStatus:500}), 'response_unknown');
assert.equal(view.responseOutcome({httpStatus:503}), 'response_unknown');
assert.equal(view.responseOutcome({}), 'response_unknown');
assert.equal(view.responseOutcome({httpStatus:409}), 'rejected');
assert.equal(view.responseOutcome({},true), 'unavailable');
// Distinct literal entity names must not collapse into the same field address.
assert.notEqual(view.pointer(['bindings','x/y']), view.pointer(['bindings','x','y']));
assert.equal(view.pointer(['bindings','x/y~z','well']), '/bindings/x~1y~0z/well');
"""
    result = subprocess.run([shutil.which('node'),'--input-type=module','-e',script],
        cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr
