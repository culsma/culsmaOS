"""Per-test station provisioning, inherited by CLI subprocesses."""
import pytest


@pytest.fixture(autouse=True)
def isolated_station(tmp_path, monkeypatch):
    monkeypatch.setenv("CULSMA_OS_STATION_ROOT", str(tmp_path / "station"))
    monkeypatch.setenv("CULSMA_OS_STATION_ID", "test-station")
