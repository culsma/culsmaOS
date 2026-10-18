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
from .support import FakeSessionFactory

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


class TestProgramWorkspaces:
    def test_identical_local_step_ids_have_run_scoped_bindings(self, tmp_path):
        paths, compiled, _, catalog, host, repository, tasks = WorkspaceFixture().build(tmp_path)
        identities = [tasks.submit(RunRequest(c.plan, c.state)) for c in compiled]
        counted = CountingRunRepository(repository)
        query = RunWorkspaceInteractor(counted, host.codec, strict=True)
        space = SpaceInteractor(SqliteSpaceRepository(sqlite3.connect(':memory:')),
            {'station.source': WorkspaceAddress('tubes', 'A1'), 'station.target': WorkspaceAddress('tubes', 'A2')},
            {('tubes', 'A1'): 100, ('tubes', 'A2'): 100}, workspaces=query)
        snapshots = []
        for identity, c in zip(identities, compiled):
            reference = run(c.plan, StubDriver(), c.state)
            allocations = [s for p in c.plan.plans for s in p.steps if s.op == 'AllocContainer']
            snapshots.append(space.bind(identity, reference.state.artifacts['material_state'], allocations))
            space.validate_snapshot(identity, snapshots[-1].revision)
        assert [b.allocation_step_id for b in snapshots[0].bindings] == [b.allocation_step_id for b in snapshots[1].bindings]
        assert [b.well for b in snapshots[0].bindings] == ['A1', 'A2']
        assert [b.well for b in snapshots[1].bindings] == ['A2', 'A1']
        assert snapshots[0].revision != snapshots[1].revision
        assert space.routes(identities[0], {'wrong-program-step': []}) == {}
        assert len(catalog.catalog) == 2
        for _ in range(20):
            value = query.workspace_for_run(identities[0])
            value['bindings']['entry.s0::alloc']['well'] = 'not-shared'
        assert query.workspace_for_run(identities[0])['bindings']['entry.s0::alloc']['well'] == 'A1'
        assert counted.reads == 2  # Frozen metadata does not re-decode growing execution checkpoints.

    def test_admitted_workspace_survives_source_and_catalog_deletion(self, tmp_path):
        paths, compiled, path, catalog, host, repository, tasks = WorkspaceFixture().build(tmp_path)
        identity = tasks.submit(RunRequest(compiled[0].plan, compiled[0].state))
        expected = RunWorkspaceInteractor(repository, host.codec).workspace_for_run(identity)
        for source in [*paths, path]:
            source.unlink()
        catalog.freeze()  # Already frozen: deleted files must not trigger a reload.
        saved = repository.get(identity).checkpoint
        with pytest.raises(HostContractError, match='HOST_CHECKPOINT_WORKSPACE_IMMUTABLE'):
            WorkspaceCheckpointInteractor(host.codec).attach(saved, expected)
        data, _ = host.restore(saved)
        assert data['schema'] == 4 and data['group_execution'] is False
        assert RunWorkspaceInteractor(repository, host.codec).workspace_for_run(identity) == expected
        advanced = host.advance(saved)
        assert host.pending(advanced).prepared.runtime_step.op == 'Mutation'
        assert host.restore(advanced)[0]['workspace'] == expected

    @pytest.mark.parametrize('problem', ['missing-binding', 'extra-binding', 'duplicate-address', 'bad-route', 'other-labware', 'unknown-field'])
    def test_invalid_catalog_rejects_before_run_admission(self, tmp_path, problem):
        _, compiled, path, catalog, _, repository, tasks = WorkspaceFixture().build(tmp_path)
        raw = json.loads(path.read_text()); profile = raw['profiles'][0]
        if problem == 'missing-binding': profile['bindings'].pop(next(iter(profile['bindings'])))
        elif problem == 'extra-binding': profile['bindings']['wrong'] = {'labware': 'tubes', 'well': 'A3'}
        elif problem == 'duplicate-address':
            keys = list(profile['bindings']); profile['bindings'][keys[1]] = deepcopy(profile['bindings'][keys[0]])
        elif problem == 'bad-route': profile['routes']['not-an-operation'] = [{'labware': 'tubes', 'destination': 'D1'}]
        elif problem == 'other-labware':
            action = next(s for p in compiled[0].plan.plans for s in p.steps if s.op == 'Mutation')
            profile['routes'][action.step_id] = [{'labware': 'other', 'destination': 'D1'}]
        else: profile['extra'] = True
        path.write_text(json.dumps(raw))
        with pytest.raises(ValueError, match='WORKSPACE_'):
            tasks.submit(RunRequest(compiled[0].plan, compiled[0].state))
        assert repository.connection.execute('SELECT count(*) FROM os_runs').fetchone()[0] == 0

    def test_ambiguous_and_unregistered_programs_reject(self, tmp_path):
        _, compiled, path, catalog, _, _, _ = WorkspaceFixture().build(tmp_path)
        raw = json.loads(path.read_text())
        raw['profiles'][1]['program'] = raw['profiles'][0]['program']
        path.write_text(json.dumps(raw))
        with pytest.raises(ValueError, match='WORKSPACE_PROGRAM_AMBIGUOUS'): catalog.resolve(compiled[0].plan)
        raw['profiles'].pop(); path.write_text(json.dumps(raw))
        with pytest.raises(ValueError, match='WORKSPACE_PROGRAM_UNREGISTERED'): catalog.resolve(compiled[1].plan)

    @pytest.mark.parametrize('field', ['workspace', 'workspace_fingerprint', 'plan', 'group_execution', 'outer-schema'])
    def test_frozen_checkpoint_tampering_rejects(self, tmp_path, field):
        _, compiled, _, _, host, repository, tasks = WorkspaceFixture().build(tmp_path)
        identity = tasks.submit(RunRequest(compiled[0].plan, compiled[0].state))
        data = host.codec.loads(repository.get(identity).checkpoint)
        if field == 'workspace': data['workspace']['bindings']['entry.s0::alloc']['well'] = 'A3'
        elif field == 'workspace_fingerprint': data['workspace_fingerprint'] = 'wrong'
        elif field == 'plan': data['plan'] = replace(data['plan'], plans=[])
        elif field == 'group_execution': data['group_execution'] = 1
        else: data['schema'] = 3
        with pytest.raises(HostContractError, match='HOST_CHECKPOINT_'): host.restore(host.codec.dumps(data))

    def test_legacy_run_and_program_checkpoint_remain_readable(self, tmp_path):
        _, compiled, _, _, host, repository, tasks = WorkspaceFixture().build(tmp_path)
        legacy = PreparationInteractor(host).prepare(RunRequest(compiled[0].plan, compiled[0].state), 'legacy')
        assert host.restore(legacy)[0]['schema'] == 2
        assert WorkspaceCheckpointInteractor(host.codec).read(host.codec.loads(legacy)) is None
        query = RunWorkspaceInteractor(repository, host.codec)
        assert query.workspace_for_run('missing') is None
        with pytest.raises(ValueError, match='WORKSPACE_RUN_NOT_FOUND'):
            RunWorkspaceInteractor(repository, host.codec, strict=True).workspace_for_run('missing')

    def test_station_address_whitelist_cannot_be_expanded_by_a_profile(self, tmp_path):
        _, compiled, path, _, host, repository, tasks = WorkspaceFixture().build(tmp_path)
        raw = json.loads(path.read_text()); raw['profiles'][0]['bindings']['entry.s0::alloc']['well'] = 'A3'
        path.write_text(json.dumps(raw))
        identity = tasks.submit(RunRequest(compiled[0].plan, compiled[0].state))
        space = SpaceInteractor(SqliteSpaceRepository(sqlite3.connect(':memory:')),
            {'allowed': WorkspaceAddress('tubes', 'A1')}, {('tubes', 'A1'): 100, ('tubes', 'A3'): 100},
            workspaces=RunWorkspaceInteractor(repository, host.codec))
        with pytest.raises(ValueError, match='WORKSPACE_ADDRESS_UNCONFIGURED'):
            space.preview(identity, {'containers': {}})

    def test_group_envelope_is_preserved_under_schema_four(self, tmp_path):
        from .test_group_handoff import SOURCE as GROUP_SOURCE
        source = tmp_path/'group.culs'; source.write_text(GROUP_SOURCE)
        c = CompilationInteractor().compile([source]); codec = RuntimeCheckpointCodecInteractor()
        from culsma.pipeline.plan_nodes import PlanStepTree
        allocations = [s for p in c.plan.plans for s in PlanStepTree.leaves(p.steps) if s.op == 'AllocContainer']
        bindings = {s.step_id: {'labware': 'plate', 'well': f'A{i+1}'} for i, s in enumerate(allocations)}
        workspace = WorkspaceProfileInteractor().validate('group', c.plan, bindings, {})
        workspace['plan_fingerprint'] = codec.fingerprint(c.plan)
        host = HostedRuntimeInteractor()
        checkpoint = WorkspaceCheckpointInteractor(codec).attach(host.create(c.plan, c.state, 'group'), workspace)
        assert host.restore(checkpoint)[0]['group_execution'] is True
        advanced = host.advance(checkpoint)
        assert isinstance(host.pending(advanced), PendingEffectGroup)
        assert len(host.pending(advanced).members) == 8

    def test_one_shot_uses_the_same_catalog_without_changing_legacy_entry(self, tmp_path):
        _, compiled, path, _, _, _, _ = WorkspaceFixture().build(tmp_path)
        context = HostBuildContext(tmp_path/'run.sqlite3', 'fake', None, tmp_path/'artifacts', workspace_config_path=path)
        sessions = FakeSessionFactory(); app = OSApplicationFactory({'fake': sessions}).build(context)
        try:
            result = app.execute(compiled[0].plan, compiled[0].state)
            assert result.ok, result.diagnostics
            identity = result.user_result['os']['run_id']
            record = app.client.get_run(identity)
            data = app.client.execution.host.codec.loads(record.checkpoint)
            assert data['schema'] == 4 and data['workspace']['id'] == 'a'
            assert len(sessions.ports) == 1 and len(sessions.ports[0].executions) == 1
        finally: app.close()

    @pytest.mark.parametrize('routes', ['configured', 'empty'])
    def test_frozen_flex_routes_override_global_driver_routes(self, tmp_path, routes):
        root = Path(__file__).resolve().parents[1]
        source = tmp_path/'protocol.culs'
        source.write_bytes((root/'examples/magnetic-buffer-exchange/protocol.culs').read_bytes())
        raw = json.loads((root/'examples/magnetic-buffer-exchange/deck-flex.json').read_text())
        path = tmp_path/'deck.json'; path.write_text(json.dumps(raw))
        catalog = tmp_path/'workspaces.json'
        catalog.write_text(json.dumps({'schema':'culsma_program_workspaces_v1','profiles':[
            {'id':'flex','program':source.name,'bindings':raw['bindings'],
             'routes':raw['labware_moves'] if routes == 'configured' else {}}]}))
        compiled = CompilationInteractor().compile([source])
        context = HostBuildContext(tmp_path/'run.sqlite3','opentrons-simulator',path,tmp_path/'artifacts',workspace_config_path=catalog)
        app = OSApplicationFactory().build(context)
        try:
            result = app.execute(compiled.plan, compiled.state)
            session = app.host.gateway.port.session
            if routes == 'configured':
                assert result.ok, result.diagnostics
                assert len(session.motion.receipts) == 6
                assert session.motion.positions()['assay'] == 'D1'
                assert session.backend.available_tips() == 90
            else:
                assert not result.ok
                assert result.user_result['os']['preflight']['status'] == 'rejected'
                assert not session.backend.protocol.commands()
                assert not session.motion.receipts and session.backend.available_tips() == 96
        finally: app.close()
