from dataclasses import asdict
from ..models import ExecutionEvidence, AttemptRecord
from ..repositories.evidence import EvidenceRepository


class EvidenceInteractor:

    def __init__(self, repository: EvidenceRepository, events, usage=None):
        self.repository = repository
        self.events = events
        self.usage = usage

    def record_intent(self, plan, attempt_id):
        attempt = AttemptRecord(
            attempt_id,
            plan.context.run_id,
            plan.effect_id,
            plan.context.mode,
            {
                **asdict(plan.context),
                "description": plan.description,
                "step_id": plan.intent.step_id,
                **({"member_effect_ids": plan.description["member_effect_ids"]} if "member_effect_ids" in plan.description else {}),
            },
        )
        self.repository.record_intent(attempt)
        return attempt

    def find_attempt(self, effect_id):
        return self.repository.find_attempt(effect_id)

    def find_evidence(self, effect_id):
        return self.repository.find_evidence(effect_id)

    def normalize(self, attempt, receipt):
        matching = (
            receipt.mode == attempt.mode
            and receipt.step_id == attempt.context["step_id"]
            and (
                receipt.configuration_revision
                == attempt.context["configuration_revision"]
            )
        )
        outcome = receipt.outcome if matching else "unknown"
        if outcome not in {"completed", "rejected", "unknown"}:
            raise ValueError("EVIDENCE_OUTCOME_INVALID")
        return ExecutionEvidence(
            f"{attempt.attempt_id}:receipt",
            attempt.run_id,
            attempt.effect_id,
            attempt.attempt_id,
            attempt.mode,
            outcome,
            receipt.payload,
            receipt.consumed_resources,
        )

    def ingest(self, evidence):
        self.repository.ingest(evidence)
        self.synchronize_usage(evidence)
        return evidence

    def record_run_event(self, event):
        self.events.append_once(event)

    def known_consumption(self, device_id):
        totals = {}
        local = self.repository.for_device(device_id)
        for evidence in local:
            if evidence.mode != "simulation":
                continue
            for resource, count in evidence.consumed_resources.items():
                totals[resource] = totals.get(resource, 0) + count
        if self.usage:
            shared = self.usage.known(device_id, tuple(e.evidence_id for e in local))
            for resource, amount in shared.items():
                totals[resource] = totals.get(resource, 0) + amount
        return totals

    def find_attempt_by_id(self, attempt_id):
        return self.repository.find_attempt_by_id(attempt_id)

    def complete_group(self, attempt):
        identities = attempt.context.get("member_effect_ids", [])
        members = tuple(self.repository.find_evidence(identity) for identity in identities)
        if not members or any(e is None or e.outcome != "completed" or e.mode != attempt.mode or e.run_id != attempt.run_id for e in members):
            raise ValueError("GROUP_EVIDENCE_INCOMPLETE")
        return self.ingest(ExecutionEvidence(
            f"{attempt.attempt_id}:group-receipt", attempt.run_id, attempt.effect_id,
            attempt.attempt_id, attempt.mode, "completed",
            {"member_evidence_ids": [e.evidence_id for e in members], "aggregate": True}, {},
        ))


    def project_collective_members(self, attempt):
        """Derived coverage facts, never independent channel measurements."""
        shared = self.find_evidence(attempt.effect_id)
        identities = attempt.context.get("member_effect_ids", [])
        description = attempt.context.get("description", {})
        step_ids = description.get("member_step_ids", [])
        if (not description.get("collective") or shared is None or len(step_ids) != len(identities)
                or not identities or shared.run_id != attempt.run_id or shared.mode != attempt.mode):
            raise ValueError("COLLECTIVE_EVIDENCE_INCOMPLETE")
        if shared.outcome == "completed" and shared.payload.get("member_step_ids") != step_ids:
            raise ValueError("COLLECTIVE_EVIDENCE_COVERAGE_INVALID")
        facts = []
        for identity, step_id in zip(identities, step_ids):
            member_attempt = self.find_attempt(identity)
            if (member_attempt is None or member_attempt.run_id != attempt.run_id
                    or member_attempt.mode != attempt.mode or member_attempt.context.get("step_id") != step_id):
                raise ValueError("COLLECTIVE_MEMBER_INTENT_MISMATCH")
            facts.append(self.ingest(ExecutionEvidence(
                f"{member_attempt.attempt_id}:wave-receipt", attempt.run_id, identity,
                member_attempt.attempt_id, attempt.mode, shared.outcome,
                {"shared_evidence_id": shared.evidence_id, "evidence_scope": "derived_wave_member",
                 "member_step_id": step_id,
                 "shared_feedback": shared.payload.get("os_feedback")}, {})))
        return tuple(facts)


    def attempts_for_run(self, run_id):
        return self.repository.attempts_for_run(run_id)

    def synchronize_usage(self, evidence):
        if self.usage:
            attempt = self.find_attempt(evidence.effect_id)
            self.usage.record(evidence, attempt.context["device_id"])

    def synchronize_device_usage(self, device_id):
        for evidence in self.repository.for_device(device_id):
            self.synchronize_usage(evidence)


    def record_logical_completion(self, completion):
        if (completion.mode != "simulation" or completion.payload.get("device_action") is not False
                or completion.payload.get("completion_kind") != "logical"):
            raise ValueError("LOGICAL_COMPLETION_INVALID")
        self.repository.record_logical_completion(completion)
        return completion

    def find_logical_completion(self, effect_id):
        return self.repository.find_logical_completion(effect_id)

    def find_completion(self, effect_id):
        logical = self.find_logical_completion(effect_id)
        physical = self.find_evidence(effect_id)
        if logical is not None and (physical is not None or self.find_attempt(effect_id) is not None):
            raise ValueError("LOGICAL_PHYSICAL_CONFLICT")
        return logical if logical is not None else physical

    def attempts_for_device(self, device_id):
        return self.repository.attempts_for_device(device_id)


    def project_batch_member(self, parent, descriptor):
        from copy import deepcopy
        from hashlib import sha256
        import json
        stored = self.find_attempt(parent.effect_id)
        same = stored is not None and json.dumps(asdict(stored), sort_keys=True) == json.dumps(asdict(parent), sort_keys=True)
        root = self.find_evidence(parent.effect_id)
        saved = parent.context['description']['execution_batch']['members']
        if (not same or root is None
                or root.mode != 'simulation' or root.outcome != 'completed'
                or descriptor not in saved):
            raise ValueError('BATCH_MEMBER_EVIDENCE_INCOMPLETE')
        identity = descriptor['effect_id']
        child_id = parent.attempt_id + '/member/' + sha256(identity.encode()).hexdigest()[:24]
        context = {**deepcopy(parent.context), 'step_id': descriptor['step_id'],
                   'description': deepcopy(descriptor['description'])}
        context.pop('member_effect_ids', None)
        child = AttemptRecord(child_id, parent.run_id, identity, parent.mode, context)
        self.repository.record_intent(child)
        payload = {**deepcopy(root.payload), 'shared_evidence_id': root.evidence_id,
                   'completion_coverage': 'derived_from_batch', 'root_effect_id': parent.effect_id}
        if descriptor['description']['operation_kind'] == 'labware_move':
            intent = descriptor['description']['motion_intent']
            payload.update(operation_kind='labware_move', phases={'move': 'returned'},
                request={key: intent[key] for key in ('step_id','labware','source','destination','position_revision')})
        evidence = ExecutionEvidence(child_id+':receipt', parent.run_id, identity, child_id,
                                     parent.mode, 'completed', payload, {})
        self.ingest(evidence)
        return child, evidence
