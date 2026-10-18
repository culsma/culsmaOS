from culsma_os.device_manager.models import DeviceAccessPort
from culsma_os.workspace_manager.models import WorkspaceAccessPort
from culsma_os.driver_framework.models import DriverGatewayPort
from .models import TransferSelectionPort, TransferIntent, TransferAliquot, TransferRequest, TransferGroupIntent, TransferExecutionDecision
from culsma_os.driver_framework.models import PreparedTransferGroup
from culsma_os.workspace_manager.models import ResolvedContainerRef
from culsma.domains.constraints.contracts import CONSTRAINT_REQUIREMENTS, ConstraintRequirement
from culsma.runtime.material.refs import MaterialRefResolver
from culsma.runtime.material.units import VOLUME_TO_UL
from math import isfinite
from culsma_os.driver_framework.models import PlanContext, MaterialExpectation


class TransferInteractor:

    def __init__(
        self,
        space: WorkspaceAccessPort,
        device: DeviceAccessPort,
        gateway: DriverGatewayPort,
        device_id: str,
        selection_planners: tuple[TransferSelectionPort, ...] = (),
    ):
        self.space = space
        self.device = device
        self.gateway = gateway
        self.device_id = device_id
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
                TransferConstraintInteractor().require_supported(requirements, self.device.get(self.device_id))
                if decision.intent is not None and decision.intent.requirements != requirements:
                    raise ValueError('TRANSFER_CONSTRAINT_MAPPING_MISMATCH')
                return decision
        step = pending.prepared.driver_step
        if step.op != "Mutation":
            raise ValueError("TRANSFER_UNSUPPORTED")
        gate = step.gate or {}
        constraint = gate.get("constraint", {})
        requirements = TransferConstraintInteractor().resolve(constraint)
        TransferConstraintInteractor().require_supported(requirements, self.device.get(self.device_id))
        if (any(k in gate for k in ("env", "env_targets"))
                or set(step.args) - {"sources", "target", "_runtime_material_resolution"}):
            raise ValueError("TRANSFER_GATE_UNSUPPORTED")
        state = pending.before_material_state
        target = MaterialRefResolver.resolve_target_ref(state, step.args["target"])
        if target is None:
            raise ValueError("TRANSFER_TARGET_UNRESOLVED")
        aliquots = self.resolve_aliquots(pending, target)
        return TransferExecutionDecision(TransferIntent(
            step.step_id, ResolvedContainerRef(target), aliquots, step.span, requirements
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
            if self.is_empty_movement(delta, pending.before_material_state["containers"][identity]):
                continue
            if delta.get("mode") == "full":
                self.require_liquid_source(pending.before_material_state["containers"][identity])
            volume = self.resolve_physical_volume(delta)
            if volume > 0:
                aliquots.append(TransferAliquot(ResolvedContainerRef(identity), volume))
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
        if any(quantity.get("dimension") == "mass" for quantity in quantities.values() if isinstance(quantity, dict)):
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

    def prepare_context(self, run_id, layout, device, material_state=None):
        resources = tuple(sorted((
            *device.shared_resources,
            *(f"{device.mode}:{device.device_id}:{b.labware}:{b.well}" for b in layout.bindings),
        )))
        expectations = []
        if material_state is not None:
            for binding in layout.bindings:
                volume = material_state["containers"][binding.reference.container_id].get("volume_uL")
                if type(volume) not in {int, float} or not isfinite(volume) or volume < 0:
                    raise ValueError("TRANSFER_MATERIAL_EXPECTATION_INVALID")
                expectations.append(MaterialExpectation(binding.reference, float(volume)))
        return PlanContext(run_id, device.device_id, device.mode,
                           device.configuration_revision, layout.revision,
                           device.calibration_revision, resources, tuple(expectations))

    def preflight(self, pending, space, device, scope_id, allocation_steps, physical_positions=None):
        decision = self.resolve_execution(pending)
        intent = decision.intent
        if intent is None:
            return None
        TransferConstraintInteractor().require_supported(intent.requirements, device)
        if device.supports_transfer is False:
            raise ValueError("TRANSFER_DEVICE_UNSUPPORTED")
        kind = getattr(intent, "selection_kind", None)
        if kind is not None and kind not in device.transfer_selection_capabilities:
            raise ValueError("DRIVER_TRANSFER_SELECTION_UNSUPPORTED")
        layout = space.preview(scope_id, pending.before_material_state, allocation_steps)
        self.prepare_context(layout.run_id, layout, device, pending.before_material_state)
        return intent

    def prepare(self, request):
        pending = request.pending
        intent = self.resolve_intent(pending)
        layout = self.space.bind(request.run_id, pending.before_material_state, request.allocation_steps)
        context = self.prepare_context(request.run_id, layout, self.device.get(self.device_id), pending.before_material_state)
        return self.gateway.prepare(pending.effect_id, intent, context, layout.bindings)

    def prepare_group(self, request):
        pending = request.pending
        if not pending.members:
            raise ValueError("TRANSFER_GROUP_EMPTY")
        # Transfer members change contents, not container identity or geometry.
        layout = self.space.bind(request.run_id, pending.before_material_state, request.allocation_steps)
        context = self.prepare_context(request.run_id, layout, self.device.get(self.device_id), pending.before_material_state)
        intents = tuple(self.resolve_intent(member) for member in pending.members)
        if getattr(self.gateway, "supports_collective_execution", False):
            return self.gateway.prepare_collective_group(pending.effect_id, pending.step_id,
                tuple(m.effect_id for m in pending.members), intents, context, layout.bindings)
        plans = tuple(self.gateway.prepare(member.effect_id, self.resolve_intent(member), context, layout.bindings, completion_unit="member")
                      for member in pending.members)
        requirements = {}
        for plan in plans:
            values = plan.description.get("resource_requirements")
            if not isinstance(values, dict) or any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in values.items()):
                raise ValueError("TRANSFER_GROUP_RESOURCE_REQUIREMENTS_INVALID")
            for resource, amount in values.items():
                requirements[resource] = requirements.get(resource, 0) + amount
        return PreparedTransferGroup(
            pending.effect_id, TransferGroupIntent(pending.step_id, tuple(p.intent for p in plans)),
            context, plans,
            {"resource_requirements": requirements, "member_effect_ids": [p.effect_id for p in plans]},
        )


class MagneticTransferInteractor:
    def handles(self, pending):
        from culsma.runtime.material.contents_state import is_container_contents_index
        step = pending.prepared.runtime_step
        if "field" in (step.gate or {}).get("env", {}):
            return True
        return any(is_container_contents_index(s.get("left") if isinstance(s, dict) and s.get("kind") == "IRPair" else s)
                   for s in step.args.get("sources", []))

    def resolve_execution(self, pending):
        from copy import deepcopy
        from culsma.runtime.material.contents_state import MaterialIndexedPartsStateManager, ContentsPartSelection, is_container_contents_index
        from culsma_os.processing_engine.interactors import MagneticEnvironmentInteractor
        from .models import MagneticFlowthroughTransferIntent
        step = pending.prepared.runtime_step
        proposal = pending.prepared.material_result
        sources = step.args.get("sources", [])
        if (step.op != "Mutation" or len(sources) != 1 or proposal is None or not proposal.ok
                or proposal.delta.get("op") != "Mutation" or len(proposal.delta.get("sources", [])) != 1):
            raise ValueError("TRANSFER_MAGNETIC_SELECTION_UNSUPPORTED")
        source = sources[0]
        reference = source.get("left") if source.get("kind") == "IRPair" else source
        if not is_container_contents_index(reference):
            raise ValueError("TRANSFER_MAGNETIC_SELECTION_UNSUPPORTED")
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
        return TransferExecutionDecision(MagneticFlowthroughTransferIntent(step.step_id, ResolvedContainerRef(target),
            (TransferAliquot(source_ref, float(volume)),), step.span,
            requirements=requirements, producer_step_id=selection.state_record["step_id"]))


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
        from .models import CentrifugeSupernatantTransferIntent
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
        if any(r not in device.transfer_requirements for r in requirements):
            raise ValueError('TRANSFER_CONSTRAINT_UNSUPPORTED')
