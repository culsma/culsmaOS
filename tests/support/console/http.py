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
