"""Read-only run projection over the owning evidence and material Interactors."""
from dataclasses import asdict


class RunEvidenceInteractor:
    def __init__(self, snapshot, journal, material):
        self.snapshot, self.journal, self.material = snapshot, journal, material

    def execute(self, run_id):
        with self.snapshot:
            journal = self.journal.inspect_run(run_id)
            attempts = []
            for observation in journal.operations:
                attempt, receipt = observation.attempt, observation.evidence
                completion_id = receipt.evidence_id if receipt and receipt.outcome == 'completed' else None
                attempts.append({
                    'effect_id': attempt.effect_id, 'attempt_id': attempt.attempt_id,
                    'step_id': attempt.context.get('step_id'), 'device_id': attempt.context.get('device_id'),
                    'mode': attempt.mode, 'context': attempt.context,
                    'evidence_status': ('mismatched' if attempt.effect_id in journal.mismatched_effect_ids
                                        else 'recorded' if receipt else 'missing'),
                    'evidence': asdict(receipt) if receipt else None,
                    'registration': self.material.inspect_registration(attempt.effect_id, completion_id),
                })
            logical = [{**asdict(item),
                        'registration': self.material.inspect_registration(item.effect_id, item.completion_id)}
                       for item in journal.logical_completions]
            return {'schema': 'culsma_run_evidence_v1', 'source': 'os_records',
                    'hardware_observed': False, 'accounting': journal.accounting,
                    'consistency': 'single_evidence_material_snapshot',
                    'ordering': 'insertion_order_within_each_record_kind',
                    'attempts': attempts, 'logical_completions': logical}
