"""Certify a concrete physical ordering with the existing language material evaluator."""
from copy import deepcopy
from culsma.runtime.material.compute import MaterialCompute
from ..models import ProjectedMaterialEffect


class GroupProjectionInteractor:
    def __init__(self, codec, material=None):
        self.codec = codec
        self.material = material or MaterialCompute()

    def prepare(self, pending, waves):
        members = pending.members
        identities = [m.prepared.runtime_step.step_id for m in members]
        order = [i for wave in waves for i in wave["member_step_ids"]]
        if (len(members) != 96 or len(order) != 96 or len(set(order)) != 96
                or set(order) != set(identities)):
            raise ValueError("TRANSFER_REORDER_COVERAGE_INVALID")
        source_ids, target_ids, amounts = [], [], []
        logical = deepcopy(pending.before_material_state)
        for member in members:
            if (member.prepared.runtime_step.op != "Mutation"
                    or set(member.prepared.runtime_step.gate or {}) - {"entry_kind", "entry_name"}):
                raise ValueError("TRANSFER_REORDER_PROFILE_UNSUPPORTED")
            original = member.prepared.material_result
            if original is None or not original.ok or member.before_material_state != logical:
                raise ValueError("TRANSFER_REORDER_PROPOSAL_INVALID")
            sources = original.delta.get("sources", [])
            if (len(sources) != 1 or sources[0].get("mode") != "quantified"
                    or sources[0].get("transfer_delta", {}).get("mode") != "volume"):
                raise ValueError("TRANSFER_REORDER_PROFILE_UNSUPPORTED")
            source_ids.append(sources[0]["source"])
            target_ids.append(original.delta["target"])
            amounts.append(sources[0]["transfer_delta"]["moved_uL"])
            result = self.material.apply_step(member.prepared.runtime_step, logical)
            if not result.ok or result.material_state != original.material_state:
                raise ValueError("TRANSFER_REORDER_REFERENCE_MISMATCH")
            logical = result.material_state
        if (len(set(source_ids)) != 1 or len(set(target_ids)) != 96 or source_ids[0] in target_ids
                or len(set(amounts)) != 1 or amounts[0] <= 0):
            raise ValueError("TRANSFER_REORDER_PROFILE_UNSUPPORTED")
        by_step = dict(zip(identities, members))
        physical = deepcopy(pending.before_material_state)
        projections = []
        for step_id in order:
            member = by_step[step_id]
            before = deepcopy(physical)
            result = self.material.apply_step(member.prepared.runtime_step, physical)
            if not result.ok:
                raise ValueError("TRANSFER_REORDER_NOT_EQUIVALENT")
            physical = result.material_state
            projections.append(ProjectedMaterialEffect(member.effect_id, before, deepcopy(physical),
                self.codec.fingerprint(member.prepared.material_result.material_state)))
        if physical != logical:
            raise ValueError("TRANSFER_REORDER_NOT_EQUIVALENT")
        return tuple(projections)

    def certificate(self, pending, projections):
        return {"rule": "uniform_common_source_distinct_targets_v1",
                "initial": self.codec.fingerprint(pending.before_material_state),
                "final": self.codec.fingerprint(projections[-1].after),
                "semantic_effect_ids": [m.effect_id for m in pending.members],
                "physical_effect_ids": [p.effect_id for p in projections]}
