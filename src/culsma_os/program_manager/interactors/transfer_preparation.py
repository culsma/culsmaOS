"""Map program transfer requests to resolved pipetting preparation."""
from math import isfinite
from .transfer_intents import TransferIntentInteractor, TransferConstraintInteractor
from culsma_os.driver_framework.models import MaterialExpectation
from culsma_os.device_manager.instruments.pipetting.interactors import PipettingExecutionPreparationInteractor


class TransferPreparationInteractor(TransferIntentInteractor):
    def __init__(self, space, device, gateway, device_id, selection_planners=(), preparation=None):
        super().__init__(selection_planners)
        self.space, self.device, self.gateway, self.device_id = space, device, gateway, device_id
        self.preparation = preparation or PipettingExecutionPreparationInteractor(gateway)

    def resolve_execution(self, pending):
        from .transfer_intents import PipetteMixSelectionInteractor
        device = self.device.get(self.device_id)
        mixing = PipetteMixSelectionInteractor()
        if 'pipette_mix' in device.transfer_selection_capabilities and mixing.handles(pending):
            decision = mixing.resolve_execution(pending)
        else:
            decision = super().resolve_execution(pending)
        requirements = TransferConstraintInteractor().resolve((pending.prepared.driver_step.gate or {}).get('constraint', {}))
        self.preparation.require_supported(requirements, self.device.get(self.device_id))
        return decision

    def prepare_context(self, run_id, layout, device, material_state=None):
        expectations = []
        if material_state is not None:
            for binding in layout.bindings:
                volume = material_state['containers'][binding.reference.container_id].get('volume_uL')
                if type(volume) not in (int, float) or not isfinite(volume) or volume < 0:
                    raise ValueError('TRANSFER_MATERIAL_EXPECTATION_INVALID')
                expectations.append(MaterialExpectation(binding.reference, float(volume)))
        return self.preparation.prepare_context(run_id, layout, device, expectations)

    def preflight(self, pending, space, device, scope_id, allocation_steps, physical_positions=None):
        decision = self.resolve_execution(pending)
        intent = decision.intent
        if intent is None:
            return None
        self.preparation.validate_intent(intent, device)
        material = pending.physical_material_state()
        layout = space.preview(scope_id, material, allocation_steps)
        self.prepare_context(layout.run_id, layout, device, material)
        return intent

    def prepare(self, request):
        pending = request.pending
        intent = self.resolve_intent(pending)
        material = pending.physical_material_state()
        layout = self.space.bind(request.run_id, material, request.allocation_steps)
        context = self.prepare_context(request.run_id, layout, self.device.get(self.device_id), material)
        self.preparation.validate_intent(intent, self.device.get(self.device_id))
        return self.preparation.prepare_execution(pending.effect_id, intent, context, layout.bindings)

    def prepare_group(self, request):
        pending = request.pending
        if not pending.members:
            raise ValueError("TRANSFER_GROUP_EMPTY")
        # Transfer members change contents, not container identity or geometry.
        material = pending.members[0].physical_material_state()
        layout = self.space.bind(request.run_id, material, request.allocation_steps)
        context = self.prepare_context(request.run_id, layout, self.device.get(self.device_id), material)
        intents = tuple(self.resolve_intent(member) for member in pending.members)
        for intent in intents:
            self.preparation.validate_intent(intent, self.device.get(self.device_id))
        return self.preparation.prepare_group(pending.effect_id, pending.step_id,
            tuple(m.effect_id for m in pending.members), intents, context, layout.bindings)
