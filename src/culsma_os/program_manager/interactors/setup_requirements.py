"""Project reachable declarations through the public runtime without device effects."""
from copy import deepcopy
from culsma.pipeline.plan_nodes import PlanStepTree
from culsma.runtime.material.args import arg_string
from .semantics import HostedRuntimeInteractor
from .replay import ReplayEffectInteractor
from culsma.driver.base import DriverResult
from culsma.driver.groups import GroupDriverResult
from culsma.runtime.executor import run
from culsma_os.driver_framework.adapters.semantic import SemanticReplayDriver


class SetupRequirementsInteractor:
    def __init__(self, codec):
        self.codec = codec

    def inspect(self, checkpoint):
        data = self.codec.loads(checkpoint)
        host = HostedRuntimeInteractor()
        if any(d.severity == 'error' for d in host.validate_plan(data['plan'])):
            raise ValueError('SETUP_PROGRAM_UNSUPPORTED')
        projection = deepcopy(data['initial_state'])
        effects = SetupDeclarationProjectionInteractor(data, projection, self.codec)
        result = run(data['plan'], SemanticReplayDriver(effects), projection, max_scheduler_rounds=10000)
        if not result.ok:
            raise ValueError('SETUP_PROGRAM_UNSUPPORTED')
        effects.capture_initial_containers()
        material = {'containers': effects.containers}
        allocations = {s.step_id: s for p in data['plan'].plans for s in PlanStepTree.leaves(p.steps) if s.op == 'AllocContainer'}
        demands = []
        for identity, container in material['containers'].items():
            metadata = container.get('metadata', {})
            allocation = metadata.get('allocation_step_id')
            if allocation not in allocations or metadata.get('kind') not in {'tube', 'well'}:
                raise ValueError('SETUP_EXTERNAL_MATERIAL_UNSUPPORTED')
            step = allocations[allocation]
            row = {'allocation_id': allocation, 'container_id': identity, 'kind': metadata['kind'],
                   'name': metadata.get('allocation_name') or identity, 'capacity_uL': metadata['capacity_uL'],
                   'initial_volume_uL': container.get('volume_uL', 0),
                   'initial_contents': deepcopy(container.get('component_quantities', container.get('components', {})))}
            if metadata['kind'] == 'well':
                namespace, carrier = arg_string(step.args.get('container_namespace')), arg_string(step.args.get('carrier_id'))
                from culsma_os.workspace_manager.interactors import SpaceInteractor
                row.update(carrier=namespace + ':' + carrier, well=arg_string(step.args.get('carrier_position')),
                           geometry=list(SpaceInteractor.declared_geometry(step)))
            demands.append(row)
        return demands


class SetupDeclarationProjectionInteractor(ReplayEffectInteractor):
    """Keep each container's initial declaration, before projected physical effects."""
    def __init__(self, data, state, codec):
        super().__init__(data, state, codec)
        self.containers = {}

    def capture_initial_containers(self):
        for identity, container in self.state.artifacts.get('material_state', {}).get('containers', {}).items():
            self.containers.setdefault(identity, deepcopy(container))

    def execute(self, step):
        if step.op not in self.bootstrap_ops:
            self.capture_initial_containers()
        return DriverResult(True, 'SETUP_PRIVATE_PROJECTION', {'projection_only': True})

    def execute_group(self, request):
        self.capture_initial_containers()
        return GroupDriverResult(request.source_member_ids, tuple(
            DriverResult(True, 'SETUP_PRIVATE_PROJECTION', {'projection_only': True}) for _ in request.members))
