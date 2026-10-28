from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
import sqlite3
import pytest
from culsma_os.resource_manager.interactors import SupplyReplacementInteractor, SupplyInteractionInteractor, ConsumableInteractor
from culsma_os.resource_manager.repository import SqliteSupplyLoadRepository
from culsma_os.resource_manager.models import SupplyReplacementRequest, SupplyReplacementError
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.auth.models import ConsoleAccessError


class Stock:
    def __init__(self): self.calls=0; self.saved=None; self.lost=False; self.drift=False
    def describe(self):
        return {'supported':True,'mode':'simulation','device_id':'robot','resource_id':'tips',
            'position_choices':['1','2'],'revision':'a'*64,'stock':{'token':'before','load_id':'initial','used':['1','2'],'ready':True}}
    def replace(self, request_id, revision, positions):
        self.calls+=1
        self.saved={'request_id':request_id,'load_id':request_id,'status':'applied','resource_id':'tips',
            'positions':positions,'source':'local_model','physical_observation':False}
        if self.lost: raise OSError('response lost')
        return self.saved
    def receipt(self, request_id, token, resource):
        return self.saved if self.saved else None if self.drift else {'request_id':request_id,'status':'not_applied'}


@pytest.fixture
def system(tmp_path):
    repo=SqliteSupplyLoadRepository(sqlite3.connect(tmp_path/'stock.sqlite3'))
    stock=Stock();devices=SimpleNamespace(execute=lambda:{'devices':[{'device_id':'robot','consumables':{'tips':{'known_consumed':2,'status':'recorded'}}}]})
    usecase=SupplyReplacementInteractor(repo,SimpleNamespace(guard=nullcontext),stock,devices)
    req=asdict(SupplyReplacementRequest('replace','new-box',usecase.current()['revision'],'tips',['1','2'],True))
    return SimpleNamespace(repo=repo,stock=stock,usecase=usecase,req=req)


def test_supply_request_identity(system):
    s=system
    result=s.usecase.execute('replace',s.req,'human',lambda:None)
    assert result['status']=='applied' and result['baseline']==2
    assert s.usecase.execute('replace',s.req,'human',lambda:None)==result
    for payload,origin in [({**s.req,'positions':['2']},'human'),(s.req,'other')]:
        with pytest.raises(SupplyReplacementError,match='CONFLICT'):s.usecase.execute('replace',payload,origin,lambda:None)
    assert s.stock.calls==1
    with pytest.raises(ValueError,match='CONFLICT'):s.repo.settle('new-box','rejected',{})


def test_supply_lost_response_reconciliation(system):
    s=system;s.stock.lost=True
    assert s.usecase.execute('replace',s.req,'human',lambda:None)['status']=='applying'
    with pytest.raises(ValueError,match='UNRESOLVED'):s.usecase.require_settled()
    restarted=SupplyReplacementInteractor(s.repo,s.usecase.guard,s.stock,s.usecase.devices)
    assert restarted.execute('status',{'request_id':'new-box'},'human',lambda:None)['status']=='applied'
    assert s.stock.calls==1 and len(s.repo.records())==1


def test_supply_busy_and_unknown_gate(system):
    s=system
    def busy():raise ValueError('BUSY')
    with pytest.raises(ValueError,match='BUSY'):s.usecase.execute('replace',s.req,'human',busy)
    assert not s.repo.records() and not s.stock.calls
    with pytest.raises(ValueError,match='STALE'):s.usecase.execute('replace',{**s.req,'expected_revision':'b'*64},'human',lambda:None)
    s.stock.lost=True;s.usecase.execute('replace',s.req,'human',lambda:None);s.stock.saved=None;s.stock.drift=True
    assert s.usecase.execute('status',{'request_id':'new-box'},'human',lambda:None)['status']=='applying'
    stock=ConsumableInteractor(SimpleNamespace(get=lambda _:SimpleNamespace(consumable_capacities={'tips':2})),SimpleNamespace(known_consumption=lambda _:{}),s.repo)
    with pytest.raises(ValueError,match='UNRESOLVED'):stock.require('another-device',{'tips':1})
    s.stock.drift=False
    assert s.usecase.execute('status',{'request_id':'new-box'},'human',lambda:None)['status']=='rejected'
    s.usecase.require_settled();assert s.stock.calls==1


def test_supply_auth_and_mcp(system):
    s=system;tokens=TokenInteractor(SessionCredentialRepository());calls=[]
    class Resident:
        def execute(self,payload):calls.append(payload);return {'ok':True}
    entry=SupplyInteractionInteractor(tokens,Resident())
    request=SupplyReplacementRequest(**s.req)
    for credential in [tokens.issue_console_session(),tokens.issue_automation_session()]:
        assert entry.execute('Bearer '+credential,request)=={'ok':True}
    assert [r['supply_origin'] for r in calls]==['local-console-process','local-mcp-process']
    with pytest.raises(ConsoleAccessError):entry.execute('Bearer '+tokens.issue_renderer_session(),request)
    with pytest.raises(SupplyReplacementError):entry.execute('Bearer '+tokens.issue_console_session(),replace(request,simulation_acknowledged=False))
    assert len(calls)==2


def test_new_load_restores_cursor_even_when_consumption_count_is_unchanged():
    from culsma_os.device_manager.interactors import DeviceInteractor
    calls=[]
    port=SimpleNamespace(restore_consumables=lambda value:calls.append(dict(value)))
    device=DeviceInteractor(None,port)
    device.consumables=SimpleNamespace(restore=lambda port,identifier:{'tips':0})
    device.restore_consumables('robot',None)
    device.restore_consumables('robot',None)
    assert calls==[{'tips':0},{'tips':0}]


def test_supply_unknown_accounting_cannot_be_replaced(system):
    s=system;s.usecase.devices.execute=lambda:{'devices':[]}
    with pytest.raises(ValueError,match='ACCOUNTING_UNAVAILABLE'):s.usecase.execute('replace',s.req,'human',lambda:None)
    assert not s.repo.records() and not s.stock.calls
