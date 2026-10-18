"""Generic OS request mapping must not inherit a particular device's limitations."""

from pathlib import Path
import ast
import pytest
from culsma.runtime.state import init_state
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.processing_engine.interactors import AgitationPreparationInteractor, CentrifugePreparationInteractor
from culsma_os.processing_engine.models import CentrifugeIntent
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


class CentrifugeMappingFixture:
    def pending(self, tmp_path, drive='500g', duration='1s', target='w', environment=False):
        source='let p=plate(format="96well",capacity=200uL); let w=p[A1:B1];'
        action=f'agit(sample={target},mode=centrifuge,drive={drive},duration={duration});'
        source += ('with env(thermal=22C,duration=1s) {'+action+'}' if environment else action)
        plan=TransferMatrixFixture().compile(source,tmp_path)
        host=HostedRuntimeInteractor()
        checkpoint=host.advance(host.create(plan,init_state(plan),'test'))
        return host.pending(checkpoint)
