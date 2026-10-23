"""Read leading declarations through the language runtime; stop before device effects."""
from copy import deepcopy
from culsma.pipeline.plan_nodes import PlanStepTree
from culsma.runtime.material.args import arg_string
from .semantics import HostedRuntimeInteractor


class SetupRequirementsInteractor:
    def __init__(self, codec):
        self.codec = codec

    def inspect(self, checkpoint):
        data = self.codec.loads(checkpoint)
        host = HostedRuntimeInteractor()
        initial = host.create(data['plan'], data['initial_state'], data['scope_id'])
        projected, _ = host.restore(host.advance(initial))
        if any(d.severity == 'error' for d in projected['diagnostics']):
            raise ValueError('SETUP_PROGRAM_UNSUPPORTED')
        material = projected['state'].artifacts.get('material_state', {'containers': {}})
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
