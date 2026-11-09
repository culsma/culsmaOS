"""Actual CLI and official MCP client against real Hamilton rules and SQLite."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.support.paths import ROOT


@pytest.mark.skipif(not os.environ.get('CULSMA_OS_MCP_SDK_PATH'), reason='Explicit isolated official MCP SDK required')
def test_static_profiles_over_stdio_without_resident(tmp_path):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    driver = Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    paths = [str(ROOT/'src'), str(driver/'src'), str(driver/'agent/src'), os.environ['CULSMA_OS_MCP_SDK_PATH']]
    # Never propagate unrelated service credentials into a test subprocess.
    env = {key: value for key, value in os.environ.items()
           if not any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY'))}
    env['PYTHONPATH'] = os.pathsep.join(paths)
    result = subprocess.run([sys.executable, '-m', 'tests.support.console.instrument_profiles_mcp_client',
        str(tmp_path), str(driver/'tools/local_console/fixtures/magnetic/device.json')], cwd=ROOT,
        env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'profile_tools': 5, 'saved_revisions': 2, 'hardware_operations': 0}
    assert not (tmp_path/'absent.sock').exists()
