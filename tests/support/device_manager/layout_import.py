import base64
from copy import deepcopy
from hashlib import sha256


def source(content=b'native bytes'):
    return {'name':'layout.bin','encoding':'base64','content':base64.b64encode(content).decode()}


def report(content=b'native bytes',complete=True):
    configuration={'format':'test','location':'one'}
    return {'schema':'culsma_layout_import_v1','source':{'name':'layout.bin','sha256':sha256(content).hexdigest()},
        'complete':complete,'configuration':configuration if complete else None,'candidate_configuration':configuration,
        'objects':[{'id':'rack','model':'vendor-model','category':'carrier','parent':'deck','site':'1',
            'origin_mm':[0,0,0],'angle_deg':0,'mapped':True}],
        'diagnostics':[] if complete else [{'code':'UNMAPPED','object_id':'rack','message':'Requires review'}],
        'activation':'not_applied','physical_observation':False,'scope':'Offline fixture'}


class ExternalProfile:
    def __init__(self,result=None):self.result=result or report();self.calls=[]
    def describe(self):return {'layout_import_supported':True}
    def import_layout(self,content,name):self.calls.append((content,name));return deepcopy(self.result)
    def validate(self,configuration):return {'valid':configuration==report()['configuration']}


class Discovery:
    def __init__(self,profile):self.profile=profile
    def discover(self):return {'external':self.profile},()
