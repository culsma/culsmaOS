"""Single run-state writer; device and resource facts stay with their owners."""
from dataclasses import replace
from ..models import RunRecord, RunFinalizationProof, SemanticHostPort
from culsma_os.resource_manager.models import RunReleaseConfirmation


class RunStateInteractor:
    terminal_outcomes = {"completed": "succeeded", "failed": "failed", "cancelled": "cancelled"}

    def __init__(self, repository, host: SemanticHostPort, evidence):
        self.repository, self.host, self.evidence = repository, host, evidence

    def get(self, run_id):
        record = self.repository.get(run_id)
        # Legacy terminal status did not certify cleanup. Project conservatively
        # without mutating a database during status/report reads.
        if record.body_outcome is None and record.status in self.terminal_outcomes:
            return replace(record, status="finalizing", body_outcome=self.terminal_outcomes[record.status], body_error=record.error)
        return record

    def create_run(self, run_id, checkpoint, queue_submission=None, setup_required=False):
        record = RunRecord(run_id, "awaiting_setup" if setup_required else "ready", checkpoint)
        if queue_submission is not None:
            return self.repository.save(record, queue_submission=queue_submission)
        return self.repository.save(record)

    def mark_waiting(self, run_id, checkpoint):
        record = self.get(run_id)
        if record.status != "ready" or record.body_outcome is not None:
            raise ValueError("RUN_TRANSITION_INVALID")
        return self.repository.save(replace(record, checkpoint=checkpoint, status="waiting"))

    def begin_finalization(self, run_id, checkpoint=None, outcome="succeeded", error=None):
        if outcome not in ("succeeded", "failed", "cancelled"):
            raise ValueError("RUN_BODY_OUTCOME_INVALID")
        record = self.get(run_id)
        if record.body_outcome is not None:
            return record
        return self.repository.save(replace(record, checkpoint=checkpoint or record.checkpoint,
            status="finalizing", body_outcome=outcome, error=error, body_error=error))

    def complete_finalization(self, run_id, proof):
        record = self.get(run_id)
        if not isinstance(proof, RunFinalizationProof) or (proof.run_id, proof.revision, proof.body_outcome) != (
                record.run_id, record.revision, record.body_outcome):
            raise ValueError("RUN_FINALIZATION_PROOF_INVALID")
        if record.status not in {"finalizing", "needs_reconciliation"}:
            raise ValueError("RUN_TRANSITION_INVALID")
        if proof.release is not None:
            if (not isinstance(proof.release, RunReleaseConfirmation)
                    or proof.release.run_id != run_id or proof.release.evidence_ids != proof.evidence_ids
                    or proof.release.revision > record.revision):
                raise ValueError("RUN_FINALIZATION_PROOF_INVALID")
        elif proof.evidence_ids or self.evidence is None or self.evidence.attempts_for_run(run_id):
            raise ValueError("RUN_FINALIZATION_PROOF_INVALID")
        status = {value: key for key, value in self.terminal_outcomes.items()}.get(record.body_outcome)
        if status is None:
            raise ValueError("RUN_BODY_OUTCOME_INVALID")
        return self.repository.save(replace(record, status=status,
            error=record.body_error if record.body_outcome == "failed" else None))

    def mark_ready(self, run_id, resolution):
        record = self.get(run_id)
        if record.body_outcome is not None:
            raise ValueError("RUN_TRANSITION_INVALID")
        pending = self.host.pending(record.checkpoint)
        if pending is None:
            return record
        checkpoint = self.host.resume(record.checkpoint, resolution)
        return self.repository.save(replace(record, checkpoint=checkpoint,
            status=record.status if record.status in {"paused", "cancel_requested"} else "ready", error=None))

    def register_batch(self, run_id, units, resolutions):
        record = self.get(run_id)
        if len(units) != len(resolutions) or not units:
            raise ValueError('BATCH_RESOLUTION_COVERAGE_INVALID')
        if self.host.batch_applied(record.checkpoint, tuple(unit.effect_id for unit in units)):
            return record
        if record.body_outcome is not None:
            raise ValueError('RUN_TRANSITION_INVALID')
        checkpoint = self.host.resume_batch(record.checkpoint, tuple(zip(units, resolutions)))
        return self.repository.save(replace(record, checkpoint=checkpoint,
            status=record.status if record.status in {'paused', 'cancel_requested'} else 'ready', error=None))

    def mark_reconciliation_required(self, run_id, reason):
        record = self.get(run_id)
        if record.status == "needs_reconciliation" and record.error == reason:
            return record
        return self.repository.save(replace(record, status="needs_reconciliation", error=reason))

    def restore_motion_waiting(self, run_id):
        record = self.get(run_id)
        if (record.status == "needs_reconciliation" and record.body_outcome is None
                and (record.error or "").startswith("MOTION_") and self.host.pending(record.checkpoint) is not None):
            return self.repository.save(replace(record, status="waiting", error=None))
        return record

    def mark_failed(self, run_id, reason):
        return self.begin_finalization(run_id, outcome="failed", error=reason)

    def pause_dispatch(self, run_id):
        record = self.get(run_id)
        if record.status in {"ready", "waiting"}:
            return self.repository.save(replace(record, status="paused"))
        return record

    def resume_dispatch(self, run_id):
        record = self.get(run_id)
        if record.status == "paused" and record.body_outcome is None:
            return self.repository.save(replace(record,
                status="waiting" if self.host.pending(record.checkpoint) else "ready", error=None))
        return record

    def request_cancel(self, run_id):
        record = self.get(run_id)
        if record.body_outcome is not None or record.status == "cancel_requested":
            return record
        return self.repository.save(replace(record, status="cancel_requested"))

    def note_blocked(self, run_id, reason):
        record = self.get(run_id)
        if record.status == "ready" and record.error != reason:
            return self.repository.save(replace(record, error=reason))
        return record

    def publish_pending_events(self):
        for event in self.repository.pending_events():
            if event.status in self.terminal_outcomes and self.get(event.run_id).status != event.status:
                continue  # Never publish an unverified legacy terminal claim.
            self.evidence.record_run_event(event)
            self.repository.mark_published(event.event_id)

    def replace_setup(self, run_id, checkpoint):
        record = self.get(run_id)
        if record.body_outcome is not None or record.status not in {'awaiting_setup', 'ready'}:
            raise ValueError('SETUP_STATE_INVALID')
        return self.repository.save(replace(record, checkpoint=checkpoint, status='awaiting_setup', error=None))

    def confirm_setup(self, run_id):
        record = self.get(run_id)
        if record.status == 'ready':
            return record
        if record.status != 'awaiting_setup':
            raise ValueError('SETUP_STATE_INVALID')
        return self.repository.save(replace(record, status='ready', error=None))
