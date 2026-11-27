"""Check the existing station before a full Windows product replacement."""
from contextlib import closing
import sqlite3
from pathlib import Path
import sys
import time

from culsma_os.program_manager.adapters.resident import ResidentClientAdapter


def prepare_upgrade(state):
    endpoint = state / 'station.endpoint'
    client = ResidentClientAdapter(endpoint, 5)
    if endpoint.exists():
        host = client.execute({'action': 'host-status'})
        runs = client.execute({'action': 'runs'})['runs']
        service = client.execute({
            'action': 'station-service', 'station_service_request': {'action': 'describe'},
        })
        if (host['status'] != 'ready' or host.get('blocked_run') or service['unsettled_request']
                or any(run['status'] not in {'completed', 'failed', 'aborted', 'cancelled'} for run in runs)):
            raise ValueError('STATION_NOT_IDLE')
    for workspace in ('agent', 'venus'):
        jobs = state / workspace / 'jobs' / 'jobs.sqlite3'
        if jobs.is_file():
            with closing(sqlite3.connect(jobs.resolve().as_uri() + '?mode=ro', uri=True)) as database:
                if database.execute('SELECT job_id FROM station WHERE id = 1').fetchone()[0] is not None:
                    raise ValueError('VENUS_STATION_NOT_IDLE')
    if endpoint.exists():
        client.execute({'action': 'shutdown'})
        deadline = time.monotonic() + 15
        while endpoint.exists():
            if time.monotonic() >= deadline:
                raise ValueError('STATION_SHUTDOWN_TIMEOUT')
            time.sleep(0.1)


if __name__ == '__main__':
    prepare_upgrade(Path(sys.argv[1]))
