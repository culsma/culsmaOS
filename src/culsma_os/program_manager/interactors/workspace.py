"""Program-scoped workspace admission and immutable checkpoint retrieval."""
from copy import deepcopy
from collections import OrderedDict
from ..models import HostContractError
from ..repositories.workspace import WorkspaceCatalogRepository


class WorkspaceCheckpointInteractor:
    def __init__(self, codec):
        self.codec = codec

    def attach(self, checkpoint, workspace):
        data = self.codec.loads(checkpoint)
        self.read(data)
        if data['schema'] == 4:
            raise HostContractError('HOST_CHECKPOINT_WORKSPACE_IMMUTABLE')
        data['group_execution'] = data['schema'] == 3
        data['schema'] = 4
        data['workspace'] = deepcopy(workspace)
        data['workspace_fingerprint'] = self.codec.fingerprint(workspace)
        self.read(data)
        return self.codec.dumps(data)

    def read(self, data):
        if type(data.get('schema')) is not int or data['schema'] not in {2, 3, 4}:
            raise HostContractError('HOST_CHECKPOINT_SCHEMA_UNSUPPORTED')
        if data.get('schema') != 4:
            if 'workspace' in data or 'workspace_fingerprint' in data or 'group_execution' in data:
                raise HostContractError('HOST_CHECKPOINT_WORKSPACE_INVALID: workspace requires schema 4')
            return None
        workspace = data.get('workspace')
        from culsma.pipeline.plan_nodes import PlanStepTree
        grouped = any(s.op == 'MutationGroup' for p in data['plan'].plans for s in PlanStepTree.walk(p.steps))
        if (type(data.get('group_execution')) is not bool or data['group_execution'] != grouped
                or not isinstance(workspace, dict)
                or workspace.get('schema') != 'culsma_run_workspace_v1'):
            raise HostContractError('HOST_CHECKPOINT_WORKSPACE_INVALID')
        if (self.codec.fingerprint(data['plan']) != data['plan_fingerprint']
                or workspace.get('plan_fingerprint') != data['plan_fingerprint']
                or self.codec.fingerprint(workspace) != data.get('workspace_fingerprint')):
            raise HostContractError('HOST_CHECKPOINT_WORKSPACE_MISMATCH')
        return deepcopy(workspace)

    @staticmethod
    def groups_enabled(data):
        return data.get('group_execution') is True if data.get('schema') == 4 else data.get('schema') == 3


class ProgramWorkspaceCatalogInteractor:
    def __init__(self, repository: WorkspaceCatalogRepository, compilation, profiles, codec):
        self.repository, self.compilation = repository, compilation
        self.profiles, self.codec = profiles, codec
        self.catalog = None

    def freeze(self):
        if self.catalog is not None:
            return
        base, document = self.repository.read()
        if (not isinstance(document, dict) or set(document) != {'schema', 'profiles'}
                or document['schema'] != 'culsma_program_workspaces_v1'
                or not isinstance(document['profiles'], list) or not document['profiles']):
            raise ValueError('WORKSPACE_CATALOG_INVALID')
        catalog, identities = {}, set()
        for entry in document['profiles']:
            if (not isinstance(entry, dict) or set(entry) != {'id', 'program', 'bindings', 'routes'}
                    or not isinstance(entry['program'], str) or not entry['program']):
                raise ValueError('WORKSPACE_CATALOG_INVALID')
            if not isinstance(entry['id'], str) or not entry['id'] or entry['id'] in identities:
                raise ValueError('WORKSPACE_PROFILE_INVALID')
            identities.add(entry['id'])
            compiled = self.compilation.compile([(base / entry['program']).resolve()])
            diagnostics = [*compiled.semantic.diagnostics, *compiled.typed.diagnostics, *compiled.plan.diagnostics]
            if any(d.severity == 'error' for d in diagnostics):
                raise ValueError('WORKSPACE_PROGRAM_DIAGNOSTICS_REJECTED')
            profile = self.profiles.validate(entry['id'], compiled.plan, entry['bindings'], entry['routes'])
            fingerprint = self.codec.fingerprint(compiled.plan)
            if fingerprint in catalog:
                raise ValueError('WORKSPACE_PROGRAM_AMBIGUOUS')
            catalog[fingerprint] = {**profile, 'plan_fingerprint': fingerprint}
        self.catalog = catalog

    def resolve(self, plan):
        if self.catalog is None:
            self.freeze()
        fingerprint = self.codec.fingerprint(plan)
        if fingerprint not in self.catalog:
            raise ValueError('WORKSPACE_PROGRAM_UNREGISTERED')
        return deepcopy(self.catalog[fingerprint])


class RunWorkspaceInteractor:
    def __init__(self, runs, codec, strict=False):
        self.runs, self.codec, self.strict = runs, codec, strict
        self.checkpoints = WorkspaceCheckpointInteractor(codec)
        self.frozen = OrderedDict()

    def workspace_for_run(self, run_id):
        if run_id in self.frozen:
            value = self.frozen.pop(run_id)
            self.frozen[run_id] = value
            return deepcopy(value)
        try:
            record = self.runs.get(run_id)
        except KeyError as error:
            if not self.strict:
                return None
            raise ValueError('WORKSPACE_RUN_NOT_FOUND') from error
        value = self.checkpoints.read(self.codec.loads(record.checkpoint))
        # Admission freezes this metadata once; mutable execution history is
        # verified by HostedRuntimeInteractor, not re-decoded for every location.
        self.frozen[run_id] = deepcopy(value)
        if len(self.frozen) > 64:
            self.frozen.popitem(last=False)
        return deepcopy(value)

    def invalidate(self, run_id):
        self.frozen.pop(run_id, None)
