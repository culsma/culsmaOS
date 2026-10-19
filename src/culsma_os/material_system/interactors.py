from culsma_os.program_manager.models import EffectResolution, GroupEffectResolution
from dataclasses import asdict
from .repositories.inspection import MaterialInspectionRepository
from .models import ReconciliationResult
from culsma_os.event_journal.models import LogicalCompletion
from .repositories import MaterialRepository


class MaterialInteractor:

    def __init__(self, repository: MaterialRepository, codec):
        self.repository = repository
        self.codec = codec

    def bind(self, run_id, pending, mode):
        existing = self.repository.receipt(pending.effect_id)
        if existing:
            return existing.version
        return self.repository.bind(run_id, mode, pending.before_material_state)

    def reconcile(self, pending, evidence):
        if evidence.effect_id != pending.effect_id:
            raise ValueError("MATERIAL_EFFECT_MISMATCH")
        if evidence.mode != "simulation" or evidence.outcome != "completed":
            if evidence.outcome != "rejected":
                self.repository.mark_uncertain(
                    evidence.run_id, pending.effect_id, evidence.evidence_id
                )
            return ReconciliationResult(False, reason="MATERIAL_EVIDENCE_INCOMPLETE")
        proposed = pending.prepared.material_result
        if proposed is None or not proposed.ok:
            raise ValueError("MATERIAL_PROPOSAL_INVALID")
        fingerprint = self.codec.fingerprint(proposed.material_state)
        receipt = self.repository.commit_once(
            evidence.run_id,
            evidence.mode,
            pending.effect_id,
            evidence.evidence_id,
            pending.before_material_state,
            proposed.material_state,
            fingerprint,
        )
        resolution = EffectResolution(
            pending.effect_id,
            evidence.evidence_id,
            receipt.registration_id,
            fingerprint,
            evidence.mode,
            "OS_MATERIAL_REGISTERED",
            evidence.payload,
        )
        return ReconciliationResult(True, resolution)

    def get(self, run_id):
        return self.repository.get(run_id)

    def registered(self, effect_id):
        return self.repository.receipt(effect_id) is not None

    def uncertainties(self, run_id):
        return self.repository.uncertainties(run_id)

    def reconcile_group(self, pending, evidences):
        if len(evidences) != len(pending.members):
            return ReconciliationResult(False, reason="GROUP_EVIDENCE_INCOMPLETE")
        resolutions = []
        for member, evidence in zip(pending.members, evidences):
            if evidence is None:
                return ReconciliationResult(False, reason="GROUP_EVIDENCE_INCOMPLETE")
            result = (self.reconcile_logical(member, evidence) if isinstance(evidence, LogicalCompletion)
                      else self.reconcile(member, evidence))
            if not result.ready:
                return result
            resolutions.append(result.resolution)
        return ReconciliationResult(True, GroupEffectResolution(pending.effect_id, tuple(resolutions)))

    def registered_group(self, member_ids):
        return bool(member_ids) and all(self.registered(identity) for identity in member_ids)


    def reconcile_collective_group(self, pending, evidences):
        from .models import MaterialCommitProposal
        if (len(evidences) != len(pending.members) or not evidences
                or any(e.effect_id != m.effect_id for m, e in zip(pending.members, evidences))
                or len({(e.run_id, e.mode, e.payload.get("shared_evidence_id")) for e in evidences}) != 1
                or not evidences[0].payload.get("shared_evidence_id")):
            raise ValueError("COLLECTIVE_MATERIAL_EVIDENCE_MISMATCH")
        if any(e.mode != "simulation" or e.outcome != "completed" for e in evidences):
            for member, evidence in zip(pending.members, evidences):
                self.repository.mark_uncertain(evidence.run_id, member.effect_id, evidence.evidence_id)
            return ReconciliationResult(False, reason="COLLECTIVE_EVIDENCE_INCOMPLETE")
        proposals = []
        for member, evidence in zip(pending.members, evidences):
            result = member.prepared.material_result
            if result is None or not result.ok:
                raise ValueError("MATERIAL_PROPOSAL_INVALID")
            proposals.append(MaterialCommitProposal(member.effect_id, evidence.evidence_id,
                member.before_material_state, result.material_state, self.codec.fingerprint(result.material_state)))
        receipts = self.repository.commit_group_once(evidences[0].run_id, evidences[0].mode, tuple(proposals))
        resolutions = tuple(EffectResolution(m.effect_id, e.evidence_id, r.registration_id,
            r.proposed_state_fingerprint, e.mode, "OS_MATERIAL_REGISTERED", e.payload)
            for m, e, r in zip(pending.members, evidences, receipts))
        return ReconciliationResult(True, GroupEffectResolution(pending.effect_id, resolutions))


    def mark_wave_uncertain(self, run_id, members, identity):
        for member in members:
            self.repository.mark_uncertain(run_id, member.effect_id, identity)

    def reconcile_projected_wave(self, pending, evidences, projections):
        from .models import MaterialCommitProposal
        if (len(evidences) != len(pending.members) or not evidences
                or [p.effect_id for p in projections] != [m.effect_id for m in pending.members]
                or any(e.effect_id != m.effect_id for m, e in zip(pending.members, evidences))
                or len({(e.run_id, e.mode, e.payload.get("shared_evidence_id")) for e in evidences}) != 1
                or not evidences[0].payload.get("shared_evidence_id")):
            raise ValueError("COLLECTIVE_MATERIAL_EVIDENCE_MISMATCH")
        if any(e.mode != "simulation" or e.outcome != "completed" for e in evidences):
            self.mark_wave_uncertain(evidences[0].run_id, pending.members, evidences[0].payload["shared_evidence_id"])
            return ReconciliationResult(False, reason="COLLECTIVE_EVIDENCE_INCOMPLETE")
        proposals = []
        for member, evidence, projected in zip(pending.members, evidences, projections):
            semantic = self.codec.fingerprint(member.prepared.material_result.material_state)
            if projected.semantic_state_fingerprint != semantic:
                raise ValueError("COLLECTIVE_PROJECTION_SEMANTICS_MISMATCH")
            proposals.append(MaterialCommitProposal(member.effect_id, evidence.evidence_id,
                projected.before, projected.after, self.codec.fingerprint(projected.after), semantic))
        self.repository.commit_group_once(evidences[0].run_id, evidences[0].mode, tuple(proposals))
        return ReconciliationResult(True)

    def resolve_registered_group(self, pending, evidences):
        if len(evidences) != len(pending.members) or not evidences:
            return ReconciliationResult(False, reason="GROUP_EVIDENCE_INCOMPLETE")
        resolutions = []
        for member, evidence in zip(pending.members, evidences):
            receipt = self.repository.receipt(member.effect_id)
            semantic = self.codec.fingerprint(member.prepared.material_result.material_state)
            if (evidence is None or evidence.effect_id != member.effect_id or evidence.outcome != "completed"
                    or evidence.mode != "simulation" or receipt is None or receipt.evidence_id != evidence.evidence_id
                    or (receipt.semantic_state_fingerprint or receipt.proposed_state_fingerprint) != semantic):
                return ReconciliationResult(False, reason="GROUP_REGISTRATION_INCOMPLETE")
            resolutions.append(EffectResolution(member.effect_id, evidence.evidence_id, receipt.registration_id,
                                               semantic, evidence.mode, "OS_MATERIAL_REGISTERED", evidence.payload))
        mode, state, _ = self.repository.get(evidences[0].run_id)
        if mode != "simulation" or self.codec.fingerprint(state) != self.codec.fingerprint(pending.members[-1].prepared.material_result.material_state):
            raise ValueError("COLLECTIVE_FINAL_STATE_MISMATCH")
        return ReconciliationResult(True, GroupEffectResolution(pending.effect_id, tuple(resolutions)))


    def reconcile_logical(self, pending, completion):
        proposal = pending.prepared.material_result
        if (not isinstance(completion, LogicalCompletion) or completion.mode != "simulation"
                or completion.effect_id != pending.effect_id
                or completion.payload.get("device_action") is not False
                or completion.payload.get("completion_kind") != "logical"
                or proposal is None or not proposal.ok
                or completion.prepared_fingerprint != self.codec.fingerprint(pending.prepared)
                or completion.before_fingerprint != self.codec.fingerprint(pending.before_material_state)
                or completion.proposed_state_fingerprint != self.codec.fingerprint(proposal.material_state)):
            raise ValueError("MATERIAL_LOGICAL_COMPLETION_MISMATCH")
        self.bind(completion.run_id, pending, completion.mode)
        receipt = self.repository.commit_once(completion.run_id, completion.mode, pending.effect_id,
            completion.completion_id, pending.before_material_state, proposal.material_state,
            completion.proposed_state_fingerprint)
        return ReconciliationResult(True, EffectResolution(pending.effect_id, completion.completion_id,
            receipt.registration_id, completion.proposed_state_fingerprint, completion.mode,
            "OS_TRANSFER_NO_ACTION", completion.payload))


class MaterialInspectionInteractor:
    def __init__(self, repository: MaterialInspectionRepository):
        self.repository = repository

    def inspect_registration(self, effect_id, completion_id):
        receipt = self.repository.receipt(effect_id)
        if receipt is None:
            return {'status': 'not_recorded', 'receipt': None}
        matched = receipt.effect_id == effect_id and completion_id is not None and receipt.evidence_id == completion_id
        return {'status': 'registered' if matched else 'unmatched', 'receipt': asdict(receipt)}
