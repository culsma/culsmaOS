"""Bridge program steps to public device preparation services."""
from .processing_intents import ThermalHoldPreparationInteractor


class ProcessingPreparationInteractor:
    def __init__(self, space, device, gateway, device_id, intent_planners=None,
                 *, devices):
        self.space, self.device, self.device_id = space, device, device_id
        self.intent_planners = ({'env_hold': ThermalHoldPreparationInteractor()}
                                if intent_planners is None else dict(intent_planners))
        self.devices = devices

    def resolve_intent(self, pending):
        planner = self.intent_planners.get(pending.prepared.runtime_step.op)
        if planner is None:
            raise ValueError('PROCESSING_OPERATION_UNSUPPORTED')
        return planner.resolve_intent(pending)

    def prepare(self, request):
        intent = self.resolve_intent(request.pending)
        layout = self.space.bind(request.run_id, request.pending.before_material_state, request.allocation_steps)
        return self.devices.prepare_execution(request.pending.effect_id, intent, request.run_id, layout,
                                              self.device.get(self.device_id))

    def preflight(self, pending, space, device, scope_id, allocation_steps, physical_positions=None):
        intent = self.resolve_intent(pending)
        layout = space.preview(scope_id, pending.before_material_state, allocation_steps)
        return self.bind_intent(intent, layout, device, physical_positions)[0]

    def bind_intent(self, intent, layout, device, physical_positions=None):
        return self.devices.bind_intent(intent, layout, device, physical_positions)
