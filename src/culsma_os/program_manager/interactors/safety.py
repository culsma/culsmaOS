"""Authoritative completion and safe-stop facts for the configured execution mode."""
class RunSafetyInteractor:
    def __init__(self, tasks, execution, evidence, material, conditions=None, motions=None):
        self.tasks, self.execution = tasks, execution
        self.evidence, self.material = evidence, material
        self.conditions = conditions
        self.motions = motions

    def require_run(self, run_id):
        return self.tasks.get(run_id)

    def release_proof(self, run_id):
        if self.conditions is not None and self.conditions.outstanding(run_id):
            return None
        return self.effects_release_proof(run_id)

    def effects_release_proof(self, run_id):
        record = self.tasks.get(run_id)
        if self.evidence.cancellation_requested(run_id):
            return self.cancellation_release_proof(run_id, record)
        if record.body_outcome is None and record.status != "cancel_requested":
            return None
        if self.material.uncertainties(run_id):
            return None
        if record.body_outcome == "succeeded" and (self.execution.pending(run_id) is not None or not self.execution.result(run_id).ok):
            return None
        release_ids = ({self.conditions.release_id(activation) for activation in self.conditions.activations(run_id)}
                       if self.conditions is not None else set())
        evidence_ids = []
        mode = getattr(self.execution.host, "execution_mode", None) or "simulation"
        for attempt in self.evidence.attempts_for_run(run_id):
            evidence = self.evidence.find_evidence(attempt.effect_id)
            if evidence is None or evidence.mode != mode or evidence.outcome not in {"completed", "rejected"}:
                return None
            if evidence.outcome == "completed" and attempt.effect_id not in release_ids:
                member_ids = attempt.context.get("member_effect_ids")
                registered = (self.motions.registered(attempt, evidence)
                    if self.motions is not None and self.motions.is_move_attempt(attempt)
                    else self.material.registered_group(member_ids) if member_ids else self.material.registered(attempt.effect_id))
                if not registered:
                    return None
            evidence_ids.append(evidence.evidence_id)
        return {"run_id": run_id, "revision": record.revision, "mode": mode,
                "reason": "completed" if record.body_outcome == "succeeded" else "verified_safe_stop",
                "body_outcome": record.body_outcome or "cancelled",
                "evidence_ids": evidence_ids}

    def cancellation_release_proof(self, run_id, record):
        identities = []
        for attempt in self.evidence.attempts_for_run(run_id):
            stop = self.evidence.find_stop(attempt.attempt_id)
            receipt = self.evidence.find_evidence(attempt.effect_id)
            if stop is not None:
                identities.append(stop['stop_id'])
            elif receipt is not None and receipt.outcome in ('completed', 'rejected'):
                identities.append(receipt.evidence_id)
            else:
                return None
        return {'run_id': run_id, 'revision': record.revision,
                'mode': getattr(self.execution.host, 'execution_mode', None) or 'simulation',
                'reason': 'verified_safe_stop', 'body_outcome': record.body_outcome or 'cancelled',
                'evidence_ids': identities}

    def repair_system_effects(self, run_id):
        if self.motions is not None:
            self.motions.repair_completed(run_id)

    def synchronize_usage(self, run_id):
        for attempt in self.evidence.attempts_for_run(run_id):
            stop = self.evidence.find_stop(attempt.attempt_id)
            if stop:
                self.evidence.synchronize_stop_usage(attempt, stop)
            value = self.evidence.find_evidence(attempt.effect_id)
            if value is not None:
                self.evidence.synchronize_usage(value)
