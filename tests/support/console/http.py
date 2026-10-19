import copy
import http.client
import json
import threading


class ResidentReadFixture:
    def __init__(self):
        self.calls = []
        self.responses = {
            'host-status': {'status': 'ready', 'blocked_run': None},
            'device-status': {'source': 'os_records', 'hardware_observed': False,
                              'devices': [], 'resources': {}},
            'runs': {'runs': []},
            'run-evidence': {'schema': 'culsma_run_evidence_v1', 'attempts': [], 'logical_completions': []},
            'status': {'run_id': 'run-1', 'status': 'completed', 'result': {}},
        }
        self.failure = None

    def execute(self, payload):
        self.calls.append(dict(payload))
        if self.failure:
            raise self.failure
        return copy.deepcopy(self.responses[payload['action']])


class ConsoleHTTPHarness:
    def __init__(self, server):
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        assert not self.thread.is_alive()

    def request(self, method, path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            payload = response.read()
            if payload and response.getheader('Content-Type', '').startswith('application/json'):
                payload = json.loads(payload)
            return response.status, dict(response.getheaders()), payload
        finally:
            connection.close()


class ConsoleProtocolHarness:
    """Run the official SDK in its normal CLI process, with bounded cleanup."""
    def __init__(self, directory, profile):
        from pathlib import Path
        from uuid import uuid4
        from tests.support.paths import ROOT
        from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
        self.directory, self.profile, self.root = directory, profile, ROOT
        self.endpoint = Path('/private/tmp')/('culsma-console-test-'+uuid4().hex[:12]+'.sock')
        self.database = directory/'os.sqlite3'
        self.client = ResidentClientAdapter(self.endpoint, 5)
        self.process, self.log = None, None

    def __enter__(self):
        import subprocess
        import sys
        self.log = (self.directory/'resident.log').open('w')
        self.process = subprocess.Popen([sys.executable,'-m','culsma_os.cli','serve',
            '--socket',str(self.endpoint),'--host-db',str(self.database),
            '--driver-config',str(self.root/'examples'/self.profile/'deck.json'),
            '--artifacts-dir',str(self.directory/'artifacts')], stdout=self.log,stderr=subprocess.STDOUT)
        try:
            self.wait(lambda: self.client.execute({'action':'host-status'})['status']=='ready', 30)
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def wait(self, predicate, timeout):
        import time
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            if self.process.poll() is not None:
                raise AssertionError('Resident process exited; inspect resident.log')
            try:
                if predicate():
                    return
                state = self.client.execute({'action':'host-status'})
                if state['status']=='failed':
                    raise AssertionError(str(state))
            except OSError:
                pass
            time.sleep(.2)
        raise AssertionError('Resident process timed out; inspect resident.log')

    def __exit__(self, *args):
        import subprocess
        try:
            if self.process and self.process.poll() is None:
                try:
                    self.client.execute({'action':'shutdown'})
                except (OSError,ValueError):
                    self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            if self.log:
                self.log.close()
            self.endpoint.with_name(self.endpoint.name+'.host.lock').unlink(missing_ok=True)
