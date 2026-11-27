from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HAMILTON_TRANSFER = ROOT / "tests/fixtures/driver_framework/hamilton"


def station_layout_fixture():
    """Resolve the site layout supplied for native import acceptance."""
    import os
    fixture = os.environ.get("CULSMA_OS_TEST_HAMILTON_LAYOUT")
    if not fixture or not Path(fixture).is_file():
        raise FileNotFoundError("Set CULSMA_OS_TEST_HAMILTON_LAYOUT to the station acceptance layout")
    return Path(fixture)
