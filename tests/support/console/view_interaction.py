from types import SimpleNamespace

STATE = {'view':'workstation','entity_id':None,'selected_entity_id':None,'dirty':False,'busy':False}

class Observation:
    def __init__(self): self.calls=[]
    def execute(self, request):
        self.calls.append(request)
        if request.resource=='run':
            return SimpleNamespace(data={'run_id':request.run_id,'status':'completed'})
        return SimpleNamespace(data={'layout':{'status':'available','layout':{
            'definition':{'objects':[{'id':'plate'}]},'configuration':{}}}})


