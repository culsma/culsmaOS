from dataclasses import replace
from pathlib import Path
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext, RunControlRequest, HostContractError
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.verification import CheckpointVerificationInteractor
from tests.support.common import FakeSessionFactory, ProgramFixture
import culsma_os.program_manager.interactors.semantics as semantics


class ChangedSessionFactory(FakeSessionFactory):
    def build(self, context):
        port, snapshot, positions, capacities, mapper = super().build(context)
        return port, replace(snapshot, configuration_revision="r2"), positions, capacities, mapper
