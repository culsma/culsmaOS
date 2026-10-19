import hashlib
import json
from tests.support.common import FakeSessionFactory


class RebuildSessionFixture(FakeSessionFactory):
    def build(self, context):
        assert all(port.closed for port in self.ports), 'Overlapping workers'
        if context.config_path and json.loads(context.config_path.read_text()).get('fail_start'):
            raise ValueError('FIXTURE_STARTUP_FAILURE')
        return super().build(context)


def activation_payload(resident,configuration,request_id='apply-test',expected=None):
    fingerprint=hashlib.sha256(json.dumps(configuration,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'action':'configure','request_id':request_id,'driver':'fake','configuration':configuration,
            'configuration_origin':{'draft_id':'test-draft','revision':1,'title':'Station','fingerprint':fingerprint},
            'configuration_fingerprint':expected or resident.client.execute({'action':'configuration-status'})['active']['fingerprint']}
