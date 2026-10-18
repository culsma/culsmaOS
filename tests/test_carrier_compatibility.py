"""Carrier identity is language-owned; placement and checkpoint admission are OS-owned."""
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.models import HostContractError
from culsma_os.workspace_manager.interactors import SpaceInteractor,LabwareMotionInteractor
from culsma_os.workspace_manager.repository import SqliteSpaceRepository
from .test_transfer_matrix import TransferMatrixFixture


class CarrierCompatibilityFixture:
    source='''let p=plate(label="Same",format="96well",carrier_id="Same",capacity=100uL);
let q=plate(label="Same",format="96well",carrier_id="Same",capacity=100uL);
let a=p[A1];let b=q[A1];'''

    def build(self,directory,source=None):
        plan=TransferMatrixFixture().compile(source or self.source,directory)
        result=run(plan,StubDriver(),init_state(plan));assert result.ok,result.diagnostics
        allocations=[s for p in plan.plans for s in p.steps if s.op=='AllocContainer']
        positions={s.step_id:SimpleNamespace(labware=f'plate{i}',well='A1') for i,s in enumerate(allocations)}
        space=SpaceInteractor(SqliteSpaceRepository(sqlite3.connect(':memory:')),positions,
            {(f'plate{i}','A1'):100 for i in range(len(positions))},
            {f'plate{i}':(8,12) for i in range(len(positions))})
        return plan,result.state.artifacts['material_state'],allocations,space


class TestCarrierCompatibility:
    @pytest.mark.parametrize('loop',[False,True])
    def test_distinct_instances_bind_independently(self,tmp_path,loop):
        source='protocol T { repeat i in schedule(start=1,end=2,step=1) { let p=plate(label="Same",format="96well",carrier_id="Same",capacity=100uL);let a=p[A1]; } } T();' if loop else None
        _,state,steps,space=CarrierCompatibilityFixture().build(tmp_path,source)
        snapshot=space.bind('run',state,steps)
        assert len(snapshot.bindings)==2
        assert len({b.carrier_instance_id for b in snapshot.bindings})==2
        assert len({b.carrier_id for b in snapshot.bindings})==1
        assert space.repository.get('run')==snapshot
        space.validate_snapshot('run',snapshot.revision)

    @pytest.mark.parametrize('problem',['split','collision','malformed','unregistered'])
    def test_identity_conflicts_remain_rejected(self,tmp_path,problem):
        _,state,steps,space=CarrierCompatibilityFixture().build(tmp_path)
        entries=list(state['containers'].values())
        if problem=='split':entries[1]['metadata']['plate_ref']=deepcopy(entries[0]['metadata']['plate_ref'])
        elif problem=='collision':
            space.positions[steps[1].step_id]=SimpleNamespace(labware='plate0',well='A2')
            space.capacities['plate0','A2']=100
            steps[1]=replace(steps[1],args={**steps[1].args,'carrier_position':{'kind':'IRString','value':'A2'}})
        elif problem=='malformed':entries[0]['metadata']['plate_ref']['id']=None
        else:state['plates'].clear()
        with pytest.raises(ValueError):space.preview('run',state,steps)

    def test_legacy_binding_roundtrip_does_not_invent_membership(self,tmp_path):
        _,state,steps,space=CarrierCompatibilityFixture().build(tmp_path,
            'let p=plate(format="96well",capacity=100uL);let a=p[A1];')
        state.pop('plates')
        for c in state['containers'].values():c['metadata'].pop('plate_ref')
        snapshot=space.bind('run',state,steps)
        assert snapshot.bindings[0].carrier_instance_id is None
        connection=space.repository.connection
        raw=json.loads(connection.execute('select snapshot from os_layouts').fetchone()[0])
        for binding in raw['bindings']:binding.pop('carrier_instance_id')
        connection.execute('update os_layouts set snapshot=?',(json.dumps(raw),))
        assert space.repository.get('run')==snapshot
        assert all('plate_ref' not in c['metadata'] for c in state['containers'].values())

    @pytest.mark.parametrize('status',['completed','skipped','waiting'])
    def test_initial_state_and_checkpoint_contract(self,tmp_path,status):
        plan,_,_,_=CarrierCompatibilityFixture().build(tmp_path)
        host=HostedRuntimeInteractor();state=init_state(plan)
        state.step_status[next(iter(state.step_status))]=status
        with pytest.raises(HostContractError,match='HOST_INITIAL_STATE_NOT_FRESH'):host.create(plan,state,'new-run')
        for field in ('locks','history'):
            dirty=init_state(plan)
            getattr(dirty,field).update({'old':'owner'}) if field=='locks' else dirty.history.append({'old':'execution'})
            with pytest.raises(HostContractError,match='HOST_INITIAL_STATE_NOT_FRESH'):host.create(plan,dirty,'new-run')
        checkpoint=host.create(plan,init_state(plan),'run');data=host.codec.loads(checkpoint)
        assert data['carrier_contract']==1
        for invalid in (999,True,{},None):
            data['carrier_contract']=invalid
            with pytest.raises(HostContractError,match='HOST_CHECKPOINT_LANGUAGE_CONTRACT_UNSUPPORTED'):host.restore(host.codec.dumps(data))
        data.pop('carrier_contract')
        assert host.restore(host.codec.dumps(data))[0]['plan']==plan
        data['plan']=replace(plan,plans=[])
        with pytest.raises(HostContractError,match='HOST_CHECKPOINT_PLAN_MISMATCH'):host.restore(host.codec.dumps(data))

    def test_new_binding_changes_revision_when_only_instance_changes(self,tmp_path):
        _,state,steps,space=CarrierCompatibilityFixture().build(tmp_path,
            'let p=plate(format="96well",capacity=100uL);let a=p[A1];')
        first=space.preview('run',state,steps)
        reference=next(iter(state['plates'].values()));old=reference['id'];reference['id']='another-instance'
        state['plates']={'another-instance':reference}
        for c in state['containers'].values():c['metadata']['plate_ref']=deepcopy(reference)
        second=space.preview('run',state,steps)
        assert first.revision!=second.revision
        assert first.bindings[0].carrier_instance_id==old
