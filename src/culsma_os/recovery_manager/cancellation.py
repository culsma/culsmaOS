"""Close software ownership without inventing an experimental completion."""


class RunCancellationInteractor:
    def __init__(self, evidence, gateway):
        self.evidence, self.gateway = evidence, gateway

    def reconcile(self, run_id):
        if not self.evidence.cancellation_requested(run_id):
            return
        attempts = self.evidence.attempts_for_run(run_id)
        for attempt in attempts:
            receipt = self.evidence.find_evidence(attempt.effect_id)
            if self.evidence.find_stop(attempt.attempt_id) or (receipt and receipt.outcome in ('completed', 'rejected')):
                continue
            # Collective members share the actual parent's dispatch. Their stop
            # is derived only after that parent has a durable stop observation.
            parent = next((a for a in attempts if attempt.effect_id in a.context.get('member_effect_ids', ())
                           and self.evidence.find_stop(a.attempt_id)), None)
            if parent:
                stopped = self.evidence.find_stop(parent.attempt_id)
                proof = {'attempt_id': attempt.attempt_id, 'mode': attempt.mode, 'state': 'stopped',
                         'evidence_ref': stopped['stop_id'], 'parent_attempt_id': parent.attempt_id}
            else:
                try:
                    proof = self.gateway.cancel_attempt(attempt)
                except ValueError as error:
                    if str(error) == 'DEVICE_CANCELLATION_UNSUPPORTED' and receipt is None:
                        continue  # Existing synchronous devices may still finish this call.
                    raise
            self.evidence.record_stop(attempt, proof)

    def stopped_fault_requires_cancellation(self, run_id):
        """A stopped device fault ends dispatch; normal cancellation still verifies ownership."""
        from culsma_os.driver_framework.interactors import DeviceFaultInteractor
        for attempt in self.evidence.attempts_for_run(run_id):
            receipt = self.evidence.find_evidence(attempt.effect_id)
            if (receipt is None or receipt.outcome != 'unknown' or receipt.mode != 'physical'
                    or receipt.attempt_id != attempt.attempt_id or receipt.run_id != run_id):
                continue
            try:
                faults = DeviceFaultInteractor().validate(receipt.payload.get('faults', []))
            except (ValueError, TypeError, KeyError):
                continue
            if any(f.get('basis') == 'device_feedback' and f.get('source') == 'driver'
                   and f.get('stop_observation', {}).get('state') == 'confirmed_stopped' for f in faults):
                return True
        return False
