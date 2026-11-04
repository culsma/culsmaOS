from ..models import SemanticHostPort
from copy import deepcopy


class ExecutionHostInteractor:

    def __init__(self, tasks, host: SemanticHostPort, state, codec=None, material=None):
        self.tasks = tasks
        self.host = host
        self.state = state
        self.material = material
        from .codec import RuntimeCheckpointCodecInteractor
        self.codec = codec or RuntimeCheckpointCodecInteractor()

    def advance(self, run_id):
        record = self.tasks.get(run_id)
        if record.status != "ready":
            return record
        if self.tasks.setup is not None:
            self.tasks.setup.require_dispatch(run_id)
        checkpoint = self.host.advance(record.checkpoint)
        data, _ = self.host.restore(checkpoint)
        if data["pending"]:
            return self.state.mark_waiting(run_id, checkpoint)
        outcome = "succeeded" if self.host.result(checkpoint).ok else "failed"
        if outcome == 'succeeded' and self.material is not None and data['confirmed']:
            last = data['confirmed'][-1].resolution
            from ..models import GroupEffectResolution
            if isinstance(last, GroupEffectResolution):
                last = last.members[-1]
            self.material.adopt_declared_state(run_id, last.mode, run_id + ':final-declarations',
                last.proposed_state_fingerprint, data['state'].artifacts.get('material_state', {'containers': {}}))
        return self.state.begin_finalization(run_id, checkpoint, outcome)

    def pending(self, run_id):
        return self.host.pending(self.tasks.get(run_id).checkpoint)

    def result(self, run_id):
        return self.host.result(self.tasks.get(run_id).checkpoint)

    def allocations(self, run_id):
        """Return allocation definitions; pending material state determines existence."""
        from culsma.pipeline.plan_nodes import PlanStepTree
        data, _ = self.host.restore(self.tasks.get(run_id).checkpoint)
        return tuple(
            deepcopy(step)
            for protocol in data["plan"].plans
            for step in PlanStepTree.leaves(protocol.steps)
            if step.op == "AllocContainer"
        )


    def preflight_report(self, run_id):
        return deepcopy(self.host.restore(self.tasks.get(run_id).checkpoint)[0].get("preflight"))

    def status(self, run_id):
        return self.tasks.get(run_id).status

    def plan(self, run_id):
        return deepcopy(self.host.restore(self.tasks.get(run_id).checkpoint)[0]["plan"])


    def project_batch(self, run_id):
        from .batch import BatchProjectionInteractor
        return BatchProjectionInteractor(self.host).prepare(self.tasks.get(run_id).checkpoint)


    def batch_initial_material(self, members):
        """Workspace reservation only; never registers projected future material."""
        containers, plates = {}, {}
        for member in members:
            for identity, container in member.before_material_state.get('containers', {}).items():
                containers.setdefault(identity, deepcopy(container))
            for identity, plate in member.before_material_state.get('plates', {}).items():
                if identity in plates and plates[identity] != plate:
                    raise ValueError('BATCH_PLATE_DECLARATION_CONFLICT')
                plates[identity] = deepcopy(plate)
        return {'containers': containers, 'plates': plates}

    def describe_batch(self, units):
        return {'units': self.codec.dumps(units), 'units_fingerprint': self.codec.fingerprint(units)}

    def restore_batch(self, manifest):
        from ..models import PendingEffect, PendingEffectGroup
        units = self.codec.loads(manifest['units'])
        if (not isinstance(units, tuple) or not units
                or any(not isinstance(unit, (PendingEffect, PendingEffectGroup)) for unit in units)
                or self.codec.fingerprint(units) != manifest['units_fingerprint']):
            raise ValueError('BATCH_REPLAY_MISMATCH')
        return units


    def verify_batch_snapshot(self, run_id, manifest, units):
        from hashlib import sha256
        checkpoint = self.tasks.get(run_id).checkpoint
        if self.host.batch_applied(checkpoint, tuple(unit.effect_id for unit in units)):
            return
        if sha256(checkpoint.encode()).hexdigest() != manifest['initial_checkpoint']:
            raise ValueError('BATCH_SNAPSHOT_STALE')
