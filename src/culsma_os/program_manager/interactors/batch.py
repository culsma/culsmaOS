"""Collect typed operations in private language state, without execution claims."""
from copy import deepcopy
from culsma.driver.base import DriverResult
from culsma.driver.groups import GroupDriverResult
from culsma.pipeline.plan_nodes import PlanStepTree
from culsma.runtime.executor import run
from culsma_os.driver_framework.adapters.semantic import SemanticReplayDriver
from culsma_os.driver_framework.models import BatchOperation
from .preflight import PreflightEffectInteractor
from .replay import ReplayEffectInteractor


class BatchProjectionInteractor:
    def __init__(self, host):
        self.host = host

    def prepare(self, checkpoint):
        data, _ = self.host.restore(checkpoint)
        if data['finished']:
            return (), ()
        if self.host.preflight is None:
            raise ValueError('BATCH_PROJECTION_UNAVAILABLE')
        projection = deepcopy(data['initial_state'])
        effects = BatchProjectionEffectInteractor(data, projection, self.host.preflight, self.host.codec)
        motion = self.host.preflight.motion
        effects.motion_projection = motion.positions() if motion is not None else None
        result = run(data['plan'], SemanticReplayDriver(effects), projection,
                     max_scheduler_rounds=self.host.preflight.max_rounds)
        if not result.ok or effects.diagnostics:
            raise ValueError('BATCH_PROJECTION_REJECTED')
        if effects.units and self.host.codec.fingerprint(effects.units[0]) != self.host.codec.fingerprint(data['pending']):
            raise ValueError('BATCH_PROJECTION_PREFIX_MISMATCH')
        return tuple(effects.units), tuple(effects.operations)


class BatchProjectionEffectInteractor(PreflightEffectInteractor):
    def __init__(self, data, state, preflight, codec):
        super().__init__(data, state, preflight)
        self.codec = codec
        self.units, self.operations = [], []
        self.allocations = tuple(s for p in data['plan'].plans for s in PlanStepTree.leaves(p.steps) if s.op == 'AllocContainer')

    def collect(self, pending):
        preflight = self.preflight
        moves = ()
        if preflight.motion is not None and self.motion_projection is not None:
            revision, positions = self.motion_projection
            moves, _ = preflight.motion.route_intents(pending, self.allocations, positions, revision)
        self.validate(pending)
        if self.diagnostics or self.retained_conditions:
            raise ValueError('BATCH_RETAINED_CONDITION_UNSUPPORTED' if self.retained_conditions else 'BATCH_PROJECTION_REJECTED')
        positions = self.motion_projection[1] if self.motion_projection is not None else None
        layout = preflight.space.preview(self.data['scope_id'], pending.before_material_state, self.allocations)
        for ordinal, move in enumerate(moves):
            self.operations.append(BatchOperation(f'{pending.effect_id}/motion/{ordinal}', move, layout.bindings))
        planner = preflight.planners[pending.prepared.runtime_step.op]
        intent = planner.preflight(pending, preflight.space, preflight.snapshot,
            self.data['scope_id'], self.allocations, physical_positions=positions)
        if intent is not None:
            self.operations.append(BatchOperation(pending.effect_id, intent, layout.bindings))

    def execute(self, step):
        if step.op in self.bootstrap_ops:
            return DriverResult(True, 'BATCH_DECLARATION', {'internal': True})
        if self.cursor < len(self.data['confirmed']):
            return ReplayEffectInteractor.execute(self, step)
        pending = self.prepare_effect(step)
        self.units.append(pending)
        self.collect(pending)
        return DriverResult(True, 'BATCH_PROJECTED', {'projection_only': True})

    def execute_group(self, request):
        if self.cursor < len(self.data['confirmed']):
            return ReplayEffectInteractor.execute_group(self, request)
        pending = self.prepare_group_effect(request)
        self.units.append(pending)
        for member in pending.members:
            self.collect(member)
        return GroupDriverResult(request.source_member_ids,
            tuple(DriverResult(True, 'BATCH_PROJECTED', {'projection_only': True}) for _ in pending.members))
