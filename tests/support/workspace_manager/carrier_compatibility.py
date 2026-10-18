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
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


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
