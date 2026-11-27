"""Per-test station provisioning, inherited by CLI subprocesses."""
import pytest


@pytest.fixture(autouse=True)
def isolated_station(tmp_path, monkeypatch):
    monkeypatch.setenv("CULSMA_OS_STATION_ROOT", str(tmp_path / "station"))
    monkeypatch.setenv("CULSMA_OS_STATION_ID", "test-station")


def pytest_make_parametrize_id(config, val, argname):
    # PYTEST_CURRENT_TEST is an environment value; Windows caps it at 32767 chars.
    from hashlib import sha256
    if isinstance(val, (str, bytes)) and len(val) > 120:
        return argname + '-' + sha256(val.encode() if isinstance(val, str) else val).hexdigest()[:12]
    return None
