"""OS contract tests with an explicitly fake multi-capability device."""

from dataclasses import asdict, replace
import ast
from pathlib import Path
import pytest
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma.driver.stub import StubDriver
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.device_manager.models import DeviceConfigurationSnapshot, ExecutionFeedbackCapabilities
from culsma_os.driver_framework.interactors import NormalizedReceiptInteractor
from culsma_os.program_manager.models import HostBuildContext, RunRequest
from culsma_os.processing_engine.models import CentrifugeIntent, CentrifugeSeparationIntent
from culsma_os.processing_engine.interactors import CentrifugeMethodBindingInteractor
from culsma_os.transfer_engine.models import CentrifugeSupernatantTransferIntent
from tests.support.common import FakeDevicePort, TestAddress
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


BASE='let s=tube(capacity=200uL,load=[content(kind=formulation,type=buffer,code="BUFFER"):50uL]); let d=tube(capacity=200uL);'


SEP='sep(sample=s,program=centrifuge_program(drive=500g));'


TRANSFER='d << [s.contents[0]:40uL];'


SOURCE=BASE+SEP+TRANSFER+'return d;'


PROFILE={'profile_id':'test_method','revision':'method-r1','duration_seconds':1}


class SeparationContractPort(FakeDevicePort):
    def __init__(self, fail=False):
        super().__init__()
        self.fail, self.processing, self.transfers = fail, [], []

    def prepare(self,intent,bindings):
        self.transfers.append(intent)
        return super().prepare(intent,bindings)

    def prepare_processing(self,intent,bindings):
        assert type(intent) is CentrifugeIntent
        assert intent.method_profile is not None
        return intent

    def describe_processing(self,intent):
        return {'resource_requirements':{},'operation_kind':'centrifuge','request':asdict(intent)}

    def execute(self,plan,attempt_id):
        if not isinstance(plan,CentrifugeIntent):return super().execute(plan,attempt_id)
        self.processing.append(plan)
        self.executions.append(attempt_id)
        return {'outcome':'unknown' if self.fail else 'completed','mode':'simulation','step_id':plan.step_id,
            'configuration_revision':'r1','consumed_resources':{},'payload':{'source':'explicit-fake-contract-device',
            'physical_measurement':False,'request':asdict(plan)}}


class SeparationContractFixture:
    def __init__(self, profile=PROFILE, fail=False, selection=True):
        self.profile,self.fail,self.selection=profile,fail,selection

    def build(self,context):
        self.port=SeparationContractPort(self.fail)
        capabilities={'labware':['loaded']}
        if self.profile is not None:capabilities['method_profiles']={'centrifuge_program':self.profile}
        return (self.port,DeviceConfigurationSnapshot('fake','simulation','r1',('simulation:fake:station',),
            consumable_capacities={'tips':96},processing_capabilities={'centrifuge':{'rotor':capabilities}},
            feedback_capabilities=ExecutionFeedbackCapabilities(),
            transfer_selection_capabilities=('centrifuge_supernatant',) if self.selection else ()),
            {'entry.s0::alloc':TestAddress('loaded','A1'),'entry.s1::alloc':TestAddress('receiver','A1')},
            {('loaded','A1'):200,('receiver','A1'):200},NormalizedReceiptInteractor())

    def open(self,tmp_path,source=SOURCE):
        plan=TransferMatrixFixture().compile(source,tmp_path)
        context=HostBuildContext(tmp_path/'os.sqlite3','fake',None,tmp_path/'artifacts')
        return plan,context,OSApplicationFactory({'fake':self}).build(context)

    def waiting(self,app,plan):
        app.client.start()
        identity=app.client.submit_run(RunRequest(plan,init_state(plan)))
        app.client.lifecycle.runs.advance_ready(identity)
        pending=app.client.execution.pending(identity)
        assert pending.prepared.runtime_step.op=='sep'
        return identity,pending
