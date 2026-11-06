from culsma_os.device_manager.models import DeviceAccessPort
from culsma_os.workspace_manager.models import WorkspaceAccessPort
from culsma_os.driver_framework.models import DriverGatewayPort
from culsma_os.device_manager.instruments.pipetting.models import TransferSelectionPort, TransferIntent, TransferAliquot, TransferRequest, TransferGroupIntent, TransferExecutionDecision
from culsma_os.driver_framework.models import PreparedTransferGroup
from culsma_os.workspace_manager.models import ResolvedContainerRef
from culsma.domains.constraints.contracts import CONSTRAINT_REQUIREMENTS, ConstraintRequirement
from culsma.runtime.material.refs import MaterialRefResolver
from culsma.runtime.material.units import VOLUME_TO_UL
from math import isfinite
from culsma_os.driver_framework.models import PlanContext, MaterialExpectation


class TransferIntentInteractor:
    def __init__(self, selection_planners=()):
        self.selection_planners = tuple(selection_planners)

    def resolve_intent(self, pending):
        decision = self.resolve_execution(pending)
        if decision.intent is None:
            raise ValueError("TRANSFER_NO_DEVICE_ACTION")
        return decision.intent

    def resolve_execution(self, pending):
        for planner in self.selection_planners:
            if planner.handles(pending):
                decision = planner.resolve_execution(pending)
                requirements = TransferConstraintInteractor().resolve((pending.prepared.driver_step.gate or {}).get('constraint', {}))
                if decision.intent is not None and decision.intent.requirements != requirements:
                    raise ValueError('TRANSFER_CONSTRAINT_MAPPING_MISMATCH')
                return decision
        step = pending.prepared.driver_step
        if step.op != "Mutation":
            raise ValueError("TRANSFER_UNSUPPORTED")
        gate = step.gate or {}
        constraint = gate.get("constraint", {})
        requirements = TransferConstraintInteractor().resolve(constraint)
        if (any(k in gate for k in ("env", "env_targets"))
                or set(step.args) - {"sources", "target", "_runtime_material_resolution"}):
            raise ValueError("TRANSFER_GATE_UNSUPPORTED")
        state = pending.before_material_state
        target = MaterialRefResolver.resolve_target_ref(state, step.args["target"])
        if target is None:
            raise ValueError("TRANSFER_TARGET_UNRESOLVED")
        aliquots = self.resolve_aliquots(pending, target)
        return TransferExecutionDecision(TransferIntent(
            step.step_id, ResolvedContainerRef(pending.exclusive_physical_id(target)), aliquots, step.span, requirements
        ) if aliquots else None)

    def resolve_aliquots(self, pending, target):
        """Map ordered language-owned source deltas; do not reimplement material rules."""
        proposal = pending.prepared.material_result
        if proposal is None or not proposal.ok or proposal.delta.get("op") != "Mutation":
            raise ValueError("TRANSFER_MATERIAL_PROPOSAL_INVALID")
        sources = pending.prepared.runtime_step.args.get("sources", [])
        deltas = proposal.delta.get("sources", [])
        if not sources or len(sources) != len(deltas) or proposal.delta.get("target") != target:
            raise ValueError("TRANSFER_MATERIAL_PROPOSAL_INVALID")
        aliquots = []
        for source, delta in zip(sources, deltas):
            reference = source.get("left") if isinstance(source, dict) and source.get("kind") == "IRPair" else source
            identity = MaterialRefResolver.resolve_target_ref(pending.before_material_state, reference)
            if identity is None:
                raise ValueError("TRANSFER_SOURCE_UNRESOLVED")
            if delta.get("mode") in {"full_self_noop", "quantified_self_noop"}:
                if identity != target or delta.get("source") != identity or delta.get("target") != target:
                    raise ValueError("TRANSFER_MATERIAL_REFERENCE_MISMATCH")
                continue
            if delta.get("source") != identity or delta.get("target") != target:
                raise ValueError("TRANSFER_MATERIAL_REFERENCE_MISMATCH")
            source_container = pending.before_material_state["containers"][identity]
            if delta.get("mode") == "full" and source_container.get("metadata", {}).get("kind") == "surface":
                # Surface locations can refer to externally observed material with no liquid ledger entry.
                raise ValueError("TRANSFER_SURFACE_PICKING_UNSUPPORTED")
            if self.is_empty_movement(delta, source_container):
                continue
            if delta.get("mode") == "full":
                self.require_liquid_source(source_container)
            volume = self.resolve_physical_volume(delta)
            if volume > 0:
                source_position = pending.exclusive_physical_id(identity)
                if source_position == pending.physical_id(target):
                    raise ValueError("TRANSFER_SEPARATION_PARTS_SHARE_LOCATION")
                aliquots.append(TransferAliquot(ResolvedContainerRef(source_position), volume))
        return tuple(aliquots)

    def is_empty_movement(self, delta, source):
        for entry in source.get("component_entries", ()):
            quantity = entry.get("quantity")
            if (type(entry.get("amount")) not in {int, float} or entry["amount"] != 0
                    or (quantity is not None and (not isinstance(quantity, dict)
                        or quantity.get("status") == "unknown"
                        or type(quantity.get("value")) not in {int, float} or quantity["value"] != 0))):
                return False
        quantities = source.get("component_quantities", {})
        if any(not isinstance(q, dict) or q.get("status") == "unknown"
               or type(q.get("value")) not in {int, float} or q["value"] != 0
               for q in quantities.values()):
            return False
        if any(type(v) not in {int, float} or v != 0 for v in source.get("components", {}).values()):
            return False
        return (delta.get("mode") == "full" and all(
            type(delta.get(name)) in {int, float} and delta[name] == 0
            for name in ("moved_uL", "moved_mg", "moved_cells")
        ))

    def require_liquid_source(self, container):
        """A bulk volume proxy for dry mass is not a pipettable liquid declaration."""
        quantities = container.get("component_quantities", {})
        if any(
            quantity.get("dimension") == "mass"
            and (quantity.get("solution_solute") is not True
                 or quantity.get("cross_axis_projection") is not False)
            for quantity in quantities.values()
            if isinstance(quantity, dict)
        ):
            raise ValueError("TRANSFER_LIQUID_VOLUME_REQUIRED")
        if not any(
            quantity.get("dimension") == "volume"
            and isinstance(quantity.get("value"), (int, float))
            and not isinstance(quantity.get("value"), bool)
            and quantity["value"] > 0
            for quantity in quantities.values()
            if isinstance(quantity, dict)
        ):
            raise ValueError("TRANSFER_LIQUID_VOLUME_REQUIRED")

    def resolve_physical_volume(self, source_delta):
        """Use actual language movement for liquid and its carrier resolution for cells."""
        if source_delta.get("mode") == "full":
            volume = source_delta.get("moved_uL")
        elif source_delta.get("mode") == "quantified":
            transfer = source_delta.get("transfer_delta", {})
            unit = source_delta.get("qty", {}).get("unit")
            if transfer.get("mode") == "volume" and unit in VOLUME_TO_UL:
                volume = transfer.get("moved_uL")
            elif transfer.get("mode") == "count_resolved_volume" and unit == "cells":
                volume = transfer.get("resolved_transfer_volume_uL")
            else:
                raise ValueError("TRANSFER_LIQUID_VOLUME_REQUIRED")
        else:
            raise ValueError("TRANSFER_SELECTION_UNSUPPORTED")
        if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not isfinite(volume) or volume < 0:
            raise ValueError("TRANSFER_LIQUID_VOLUME_REQUIRED")
        return float(volume)

class MagneticTransferInteractor:
    def handles(self, pending):
        from culsma.runtime.material.contents_state import is_container_contents_index
        step = pending.prepared.runtime_step
        proposal = pending.prepared.material_result
        if proposal is not None and pending.in_place_outputs and any(
                pending.in_place_outputs.get(delta.get("source"), (None, None, None))[2] == "1"
                for delta in proposal.delta.get("sources", ())):
            return True
        if "field" in (step.gate or {}).get("env", {}):
            return True
        return any(is_container_contents_index(s.get("left") if isinstance(s, dict) and s.get("kind") == "IRPair" else s)
                   for s in step.args.get("sources", []))

    def resolve_execution(self, pending):
        from copy import deepcopy
        from culsma.runtime.material.contents_state import MaterialIndexedPartsStateManager, ContentsPartSelection, is_container_contents_index
        from .magnetic_intents import MagneticEnvironmentInteractor
        from culsma_os.device_manager.instruments.pipetting.models import MagneticFlowthroughTransferIntent
        step = pending.prepared.runtime_step
        proposal = pending.prepared.material_result
        sources = step.args.get("sources", [])
        if (step.op != "Mutation" or len(sources) != 1 or proposal is None or not proposal.ok
                or proposal.delta.get("op") != "Mutation" or len(proposal.delta.get("sources", [])) != 1):
            raise ValueError("TRANSFER_MAGNETIC_SELECTION_UNSUPPORTED")
        source = sources[0]
        reference = source.get("left") if source.get("kind") == "IRPair" else source
        if not is_container_contents_index(reference):
            return self.resolve_named_flowthrough(pending, reference)
        selection = MaterialIndexedPartsStateManager().resolve_indexed_part(
            step=step, state=deepcopy(pending.before_material_state), contents_ref=reference)
        if (not isinstance(selection, ContentsPartSelection) or selection.slot != "1"
                or selection.state_record.get("program_kind") != "magnetic_program"):
            raise ValueError("TRANSFER_MAGNETIC_FLOWTHROUGH_REQUIRED")
        source_ref = ResolvedContainerRef(selection.source_id)
        requirements = TransferConstraintInteractor().resolve((step.gate or {}).get("constraint", {}))
        MagneticEnvironmentInteractor().validate(step, pending.before_material_state, (source_ref,))
        delta = proposal.delta["sources"][0]
        target = MaterialRefResolver.resolve_target_ref(pending.before_material_state, step.args.get("target"))
        if (delta.get("op") != "contents_state_transfer" or delta.get("source") != selection.source_id
                or delta.get("selected_slot") != "1" or delta.get("dest") != target
                or delta.get("mode") not in {"contents_state_full", "contents_state_volume"} or target == selection.source_id):
            raise ValueError("TRANSFER_MAGNETIC_DELTA_UNSUPPORTED")
        volume = delta.get("moved_uL")
        if type(volume) not in {int, float} or not isfinite(volume) or volume < 0:
            raise ValueError("TRANSFER_MAGNETIC_VOLUME_REQUIRED")
        quantities = selection.part.get("component_quantities", {})
        values = [*quantities.values(), *(entry.get("quantity") for entry in selection.part.get("component_entries", []))]
        if (any(not isinstance(q, dict) or q.get("dimension") != "volume" or q.get("status") == "unknown"
                or type(q.get("value")) not in {int, float} or not isfinite(q["value"]) or q["value"] < 0
                for q in values) or (volume > 0 and not quantities)):
            raise ValueError("TRANSFER_MAGNETIC_LIQUID_REQUIRED")
        if volume == 0:
            return TransferExecutionDecision(None)
        return TransferExecutionDecision(MagneticFlowthroughTransferIntent(step.step_id,
            ResolvedContainerRef(pending.exclusive_physical_id(target)),
            (TransferAliquot(ResolvedContainerRef(pending.physical_id(selection.source_id)), float(volume)),), step.span,
            requirements=requirements, producer_step_id=selection.state_record["step_id"]))

    def resolve_named_flowthrough(self, pending, reference):
        from .magnetic_intents import MagneticEnvironmentInteractor
        from culsma_os.device_manager.instruments.pipetting.models import MagneticFlowthroughTransferIntent
        step = pending.prepared.runtime_step
        state = pending.before_material_state
        identity = MaterialRefResolver.resolve_target_ref(state, reference)
        output = (pending.in_place_outputs or {}).get(identity)
        delta, = pending.prepared.material_result.delta["sources"]
        target = MaterialRefResolver.resolve_target_ref(state, step.args.get("target"))
        if (output is None or output[2] != "1" or target is None
                or delta.get("source") != identity or delta.get("target") != target
                or pending.physical_id(target) == output[0]):
            raise ValueError("TRANSFER_MAGNETIC_FLOWTHROUGH_REQUIRED")
        if any(k in (step.gate or {}) for k in ("env", "env_layers", "env_targets")):
            MagneticEnvironmentInteractor().validate(step, state, (ResolvedContainerRef(output[0]),))
        volume = TransferIntentInteractor().resolve_physical_volume(delta)
        if volume == 0:
            return TransferExecutionDecision(None)
        TransferIntentInteractor().require_liquid_source(state["containers"][identity])
        requirements = TransferConstraintInteractor().resolve((step.gate or {}).get("constraint", {}))
        return TransferExecutionDecision(MagneticFlowthroughTransferIntent(step.step_id,
            ResolvedContainerRef(pending.exclusive_physical_id(target)),
            (TransferAliquot(ResolvedContainerRef(output[0]), volume),), step.span,
            requirements=requirements, producer_step_id=output[1]))

class CentrifugeTransferInteractor:
    def select(self, pending, reference):
        from copy import deepcopy
        from culsma.runtime.material.contents_state import MaterialIndexedPartsStateManager
        return MaterialIndexedPartsStateManager().resolve_indexed_part(
            step=pending.prepared.runtime_step, state=deepcopy(pending.before_material_state), contents_ref=reference)

    def handles(self, pending):
        from culsma.runtime.material.contents_state import is_container_contents_index, ContentsPartSelection
        for source in pending.prepared.runtime_step.args.get("sources", []):
            reference = source.get("left") if isinstance(source, dict) and source.get("kind") == "IRPair" else source
            if is_container_contents_index(reference):
                selected = self.select(pending, reference)
                if isinstance(selected, ContentsPartSelection) and selected.state_record.get("program_kind") == "centrifuge_program":
                    return True
        return False

    def resolve_execution(self, pending):
        from culsma.runtime.material.contents_state import ContentsPartSelection
        from culsma_os.device_manager.instruments.pipetting.models import CentrifugeSupernatantTransferIntent
        step, proposal = pending.prepared.runtime_step, pending.prepared.material_result
        sources = step.args.get("sources", [])
        if (step.op != "Mutation" or set(step.gate or {}) - {"entry", "entry_kind", "entry_name"}
                or len(sources) != 1 or proposal is None or not proposal.ok
                or proposal.delta.get("op") != "Mutation" or len(proposal.delta.get("sources", [])) != 1):
            raise ValueError("TRANSFER_CENTRIFUGE_SCOPE_UNSUPPORTED")
        source = sources[0]
        reference = source.get("left") if isinstance(source, dict) and source.get("kind") == "IRPair" else source
        selection = self.select(pending, reference)
        if (not isinstance(selection, ContentsPartSelection) or selection.slot != "0"
                or selection.state_record.get("program_kind") != "centrifuge_program"
                or selection.state_record.get("slot_contract", {}).get("0") != "supernatant"
                or not selection.state_record.get("step_id")):
            raise ValueError("TRANSFER_CENTRIFUGE_SUPERNATANT_REQUIRED")
        delta = proposal.delta["sources"][0]
        target = MaterialRefResolver.resolve_target_ref(pending.before_material_state, step.args.get("target"))
        if (target is None or target == selection.source_id or delta.get("op") != "contents_state_transfer"
                or delta.get("source") != selection.source_id or delta.get("selected_slot") != "0"
                or delta.get("dest") != target
                or delta.get("mode") not in {"contents_state_full", "contents_state_volume"}):
            raise ValueError("TRANSFER_CENTRIFUGE_DELTA_UNSUPPORTED")
        volume = delta.get("moved_uL")
        quantities = selection.part.get("component_quantities", {})
        values = [*quantities.values(), *(e.get("quantity") for e in selection.part.get("component_entries", []))]
        if (type(volume) not in {int, float} or not isfinite(volume) or volume < 0
                or any(not isinstance(q, dict) or q.get("dimension") != "volume" or q.get("status") == "unknown"
                       or type(q.get("value")) not in {int, float} or not isfinite(q["value"]) or q["value"] < 0 for q in values)
                or (volume > 0 and not quantities)):
            raise ValueError("TRANSFER_CENTRIFUGE_LIQUID_REQUIRED")
        if volume == 0:
            return TransferExecutionDecision(None)
        return TransferExecutionDecision(CentrifugeSupernatantTransferIntent(step.step_id, ResolvedContainerRef(target),
            (TransferAliquot(ResolvedContainerRef(selection.source_id), float(volume)),), step.span,
            producer_step_id=selection.state_record["step_id"]))

class TransferConstraintInteractor:
    def resolve(self, constraint):
        if (not isinstance(constraint, dict) or set(constraint) - {'requirements','options','requirement_types'}
                or constraint.get('options')):
            raise ValueError('TRANSFER_CONSTRAINT_INVALID')
        requirements = constraint.get('requirements', [])
        types = constraint.get('requirement_types', {})
        if not isinstance(requirements, (tuple,list)) or not isinstance(types, dict):
            raise ValueError('TRANSFER_CONSTRAINT_INVALID')
        result = []
        try:
            for requirement in requirements:
                if isinstance(requirement, ConstraintRequirement):
                    member = CONSTRAINT_REQUIREMENTS.validate(requirement)
                elif type(requirement) is str:
                    member = CONSTRAINT_REQUIREMENTS.decode(requirement)
                else:
                    raise ValueError('Nonstandard transfer requirement identity')
                if member.value not in result:
                    result.append(member.value)
            for wire,payload in types.items():
                member = CONSTRAINT_REQUIREMENTS.current.decode(payload)
                if type(member) is not ConstraintRequirement or member.value != wire or wire not in result:
                    raise ValueError('Nonstandard or mismatched transfer requirement identity')
        except (TypeError,ValueError,KeyError) as error:
            raise ValueError('TRANSFER_CONSTRAINT_INVALID') from error
        return tuple(result)

    def require_supported(self, requirements, device):
        from culsma_os.device_manager.instruments.pipetting.interactors import PipettingCapabilityInteractor
        return PipettingCapabilityInteractor().require_supported(requirements, device)
