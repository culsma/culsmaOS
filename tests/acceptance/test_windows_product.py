import sqlite3

import pytest

from tools.build_windows_product import WindowsProductBuilder
from tools.windows.prepare_upgrade import prepare_upgrade


def test_product_requires_driver_wheels_without_the_standalone_agent(tmp_path):
    wheels = [tmp_path / f'{name}-test.whl' for name in ('culsma', 'culsma_os', 'culsma_driver_hamilton')]
    for wheel in wheels:
        wheel.touch()
    builder = WindowsProductBuilder()
    assert builder.product_wheels(tmp_path) == sorted(wheels)
    (tmp_path / 'culsma_hamilton_agent-test.whl').touch()
    with pytest.raises(ValueError, match='standalone Hamilton Agent'):
        builder.product_wheels(tmp_path)


@pytest.mark.parametrize('workspace', ['agent', 'venus'])
def test_upgrade_reads_the_existing_job_reservation_without_starting_a_service(tmp_path, workspace):
    db = tmp_path / workspace / 'jobs' / 'jobs.sqlite3'
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE station (id INTEGER PRIMARY KEY, job_id TEXT)')
        connection.execute("INSERT INTO station VALUES (1, 'pending-job')")
    with pytest.raises(ValueError, match='VENUS_STATION_NOT_IDLE'):
        prepare_upgrade(tmp_path)
    with sqlite3.connect(db) as connection:
        connection.execute('UPDATE station SET job_id=NULL')
    prepare_upgrade(tmp_path)


def test_windows_product_verifies_the_hamilton_release(tmp_path, monkeypatch):
    from hashlib import sha256

    builder = WindowsProductBuilder()
    release = builder.hamilton_release()
    assert release['url'].endswith(release['filename'] + '#sha256=' + release['sha256'])
    assert release['url'].startswith('https://github.com/culsma/culsma-driver-hamilton/releases/download/')
    wheel = tmp_path / release['filename']
    wheel.write_bytes(b'repacked')
    with pytest.raises(ValueError, match='match the public release'):
        builder.verify_hamilton_wheel(tmp_path)
    pin = dict(release, sha256=sha256(wheel.read_bytes()).hexdigest())
    monkeypatch.setattr(builder, 'hamilton_release', lambda: pin)
    assert builder.verify_hamilton_wheel(tmp_path) == pin
