"""Project reachable declarations through the public runtime without device effects."""
from copy import deepcopy
from culsma.pipeline.plan_nodes import PlanStepTree
from culsma.runtime.material.args import arg_string
from .semantics import HostedRuntimeInteractor
from .replay import ReplayEffectInteractor
from .workflow_simulation import WorkflowSimulationInteractor
from culsma.driver.base import DriverResult
from culsma.driver.groups import GroupDriverResult
from culsma.runtime.executor import run
from culsma_os.driver_framework.adapters.semantic import SemanticReplayDriver


class SetupRequirementsError(ValueError):
    """A loading capability gap, with structured evidence for UI and MCP."""
    def __init__(self, code, message, items=()):
        super().__init__(code + ': ' + message)
        self.diagnostics = [{'code': code, 'message': message, 'items': list(items),
            'basis': 'language_projection', 'physical_observation': False,
            'action': 'This program needs an explicit device mapping for its separation outputs. No device operation has been dispatched.'}]


class SetupRequirementsInteractor:
    def __init__(self, codec):
        self.codec = codec

    def inspect(self, checkpoint):
        data = self.codec.loads(checkpoint)
        host = HostedRuntimeInteractor()
        if any(d.severity == 'error' for d in host.validate_plan(data['plan'], WorkflowSimulationInteractor.routes(data))):
            raise ValueError('SETUP_PROGRAM_UNSUPPORTED')
        projection = deepcopy(data['initial_state'])
        effects = SetupDeclarationProjectionInteractor(data, projection, self.codec)
        result = run(data['plan'], SemanticReplayDriver(effects), projection, max_scheduler_rounds=10000)
        if not result.ok:
            raise ValueError('SETUP_PROGRAM_UNSUPPORTED')
        effects.capture_initial_containers()
        unplaced = [output for output in effects.derived_outputs.values()
                    if output['program_kind'] != 'magnetic_program']
        if unplaced:
            raise SetupRequirementsError('SETUP_SEPARATION_OUTPUT_MAPPING_REQUIRED',
                'Named separation outputs are material fractions, not declared labware. '
                'The current execution path has no physical-location mapping for these fractions.',
                unplaced)
        material = {'containers': effects.containers}
        allocations = {s.step_id: s for p in data['plan'].plans for s in PlanStepTree.leaves(p.steps) if s.op == 'AllocContainer'}
        demands = []
        for identity, container in material['containers'].items():
            metadata = container.get('metadata', {})
            allocation = metadata.get('allocation_step_id')
            if allocation not in allocations or metadata.get('kind') not in {None, 'tube', 'well'}:
                raise ValueError('SETUP_EXTERNAL_MATERIAL_UNSUPPORTED')
            step = allocations[allocation]
            row = {'allocation_id': allocation, 'container_id': identity, 'kind': metadata.get('kind') or 'container',
                   'name': metadata.get('allocation_name') or identity, 'capacity_uL': metadata['capacity_uL'],
                   'initial_volume_uL': container.get('volume_uL', 0),
                   'initial_contents': deepcopy(container.get('component_quantities', container.get('components', {})))}
            if metadata.get('kind') == 'well':
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
        self.derived_outputs = {}

    def capture_initial_containers(self):
        for identity, container in self.state.artifacts.get('material_state', {}).get('containers', {}).items():
            if identity not in self.derived_outputs:
                self.containers.setdefault(identity, deepcopy(container))

    def record_separation_outputs(self, step):
        runtime_step = self.values.resolve_step_args(self.steps[step.step_id], self.state)
        material = self.state.artifacts.get('material_state', {'containers': {}})
        proposal = self.material.apply_step(runtime_step, material)
        if not proposal.ok:
            return  # The reference runtime reports its owning material diagnostic.
        delta = proposal.delta
        for slot, identity in delta.get('slots', {}).items():
            if identity != delta.get('source'):
                self.derived_outputs[identity] = {'container_id': identity,
                    'producer_step_id': step.step_id, 'source_container_id': delta['source'],
                    'part': slot, 'program_kind': delta.get('program_kind')}

    def execute(self, step):
        simulated = WorkflowSimulationInteractor.execute_step(self.data, step)
        if simulated is not None:
            return simulated
        if step.op == 'sep':
            self.record_separation_outputs(step)
        if step.op not in self.bootstrap_ops:
            self.capture_initial_containers()
        return DriverResult(True, 'SETUP_PRIVATE_PROJECTION', {'projection_only': True})

    def execute_group(self, request):
        self.capture_initial_containers()
        return GroupDriverResult(request.source_member_ids, tuple(
            DriverResult(True, 'SETUP_PRIVATE_PROJECTION', {'projection_only': True}) for _ in request.members))
