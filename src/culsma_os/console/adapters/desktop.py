"""Native process transport. Credentials are sent over stdin, never command arguments."""
import json
import os
from pathlib import Path
import subprocess


class NativeConsoleProcessAdapter:
    def __init__(self, executable):
        self.executable = Path(executable)

    def run(self, connection):
        with subprocess.Popen([str(self.executable)], stdin=subprocess.PIPE, text=True) as child:
            child.stdin.write(json.dumps(connection) + '\n')
            child.stdin.close()
            child.stdin = None
            return child.wait()


class ResidentProcessAdapter:
    def __init__(self, command, log_path, station_root):
        self.command, self.log_path = tuple(command), Path(log_path)
        self.station_root = Path(station_root)

    def start(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open('ab') as log:
            subprocess.Popen(self.command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, env={**os.environ, 'CULSMA_OS_STATION_ROOT': str(self.station_root)})
