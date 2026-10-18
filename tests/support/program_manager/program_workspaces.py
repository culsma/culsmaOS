"""Program-local physical mappings are frozen under the owning compiled plan."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.codec import RuntimeCheckpointCodecInteractor
from culsma_os.program_manager.interactors.preparation import PreparationInteractor
from culsma_os.program_manager.interactors.run_state import RunStateInteractor
from culsma_os.program_manager.interactors.runs import TaskInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.workspace import (
    ProgramWorkspaceCatalogInteractor, RunWorkspaceInteractor, WorkspaceCheckpointInteractor,
)
from culsma_os.program_manager.models import RunRequest, HostContractError, PendingEffectGroup, HostBuildContext
from culsma_os.program_manager.repositories.runs import SqliteTaskRepository
from culsma_os.program_manager.repositories.workspace import FileWorkspaceCatalogRepository
from culsma_os.workspace_manager.interactors import SpaceInteractor, WorkspaceProfileInteractor
from culsma_os.workspace_manager.models import WorkspaceAddress
from culsma_os.workspace_manager.repository import SqliteSpaceRepository
from tests.support.common import FakeSessionFactory


SOURCE = '''let source=tube(label="A",capacity=100uL,load=[content(kind=formulation,type=buffer,code="B"):40uL]);
let target=tube(capacity=100uL);target << [source:10uL];'''


class WorkspaceFixture:
    def build(self, directory):
        paths = [directory/'a.culs', directory/'b.culs']
        for path, label in zip(paths, ('A', 'B')):
            path.write_text(SOURCE.replace('label="A"', f'label="{label}"'))
        compiled = [CompilationInteractor().compile([path]) for path in paths]
        profiles = []
        for index, (path, item) in enumerate(zip(paths, compiled)):
            allocations = [s for p in item.plan.plans for s in p.steps if s.op == 'AllocContainer']
            bindings = {s.step_id: {'labware': 'tubes', 'well': f'A{(i+index)%2+1}'} for i, s in enumerate(allocations)}
            profiles.append({'id': path.stem, 'program': path.name, 'bindings': bindings, 'routes': {}})
        path = directory/'workspaces.json'
        path.write_text(json.dumps({'schema': 'culsma_program_workspaces_v1', 'profiles': profiles}))
        codec = RuntimeCheckpointCodecInteractor()
        catalog = ProgramWorkspaceCatalogInteractor(FileWorkspaceCatalogRepository(path),
            CompilationInteractor(), WorkspaceProfileInteractor(), codec)
        host = HostedRuntimeInteractor()
        connection = sqlite3.connect(':memory:')
        repository = SqliteTaskRepository(connection)
        tasks = TaskInteractor(repository, PreparationInteractor(host, catalog, WorkspaceCheckpointInteractor(codec)),
            RunStateInteractor(repository, host, None))
        return paths, compiled, path, catalog, host, repository, tasks


class CountingRunRepository:
    def __init__(self, delegate):
        self.delegate, self.reads = delegate, 0

    def get(self, run_id):
        self.reads += 1
        return self.delegate.get(run_id)
