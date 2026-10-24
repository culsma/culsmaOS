from ..models import SemanticHostPort
from copy import deepcopy


class ExecutionHostInteractor:

    def __init__(self, tasks, host: SemanticHostPort, state, codec=None):
        self.tasks = tasks
        self.host = host
        self.state = state
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
        return self.state.begin_finalization(run_id, checkpoint, outcome)

    def pending(self, run_id):
        return self.host.pending(self.tasks.get(run_id).checkpoint)

    def result(self, run_id):
        return self.host.result(self.tasks.get(run_id).checkpoint)

    def allocations(self, run_id):
        """Return completed allocation declarations from the verified existing checkpoint."""
        data, _ = self.host.restore(self.tasks.get(run_id).checkpoint)
        return tuple(
            deepcopy(step)
            for protocol in data["plan"].plans
            for step in protocol.steps
            if step.op == "AllocContainer"
            and data["state"].step_status.get(step.step_id) == "completed"
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
