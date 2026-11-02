"""Prepare a device plan from a resolved operation and authoritative layout."""
from culsma_os.driver_framework.models import PlanContext


class InstrumentExecutionPreparationInteractor:
    capability = None

    def __init__(self, gateway, placement=None, method_binding=None):
        self.gateway = gateway
        self.placement = placement
        self.method_binding = method_binding

    def validate_intent(self, intent, capability):
        if intent.capability != self.capability:
            raise ValueError('PROCESSING_INSTRUMENT_INTENT_MISMATCH')

    def bind_intent(self, intent, layout, device, physical_positions=None):
        bindings = {b.reference: b for b in layout.bindings}
        if len(bindings) != len(layout.bindings) or not intent.targets or any(t not in bindings for t in intent.targets):
            raise ValueError('PROCESSING_TARGET_UNBOUND')
        labwares = {bindings[t].labware for t in intent.targets}
        if len(labwares) != 1:
            raise ValueError('PROCESSING_MODULE_SCOPE')
        labware = next(iter(labwares))
        modules = [name for name, capability in device.processing_capabilities.get(intent.capability, {}).items()
                   if labware in capability['labware']]
        if self.placement is not None:
            module = self.placement.select_module(labware, tuple(modules), physical_positions)
        elif len(modules) == 1:
            module = modules[0]
        else:
            raise ValueError('PROCESSING_MODULE_UNAVAILABLE')
        if any(b.labware == labware and b.reference not in intent.targets for b in layout.bindings):
            raise ValueError('PROCESSING_COLLATERAL_EXPOSURE')
        if self.placement is not None:
            self.placement.require_module(labware, module, physical_positions)
        capability = device.processing_capabilities[intent.capability][module]
        destination = capability.get('release_destination')
        if destination is not None and physical_positions is not None and destination in physical_positions.values():
            raise ValueError('PROCESSING_RELEASE_DESTINATION_OCCUPIED')
        self.validate_intent(intent, capability)
        if self.method_binding is not None:
            intent = self.method_binding.bind(intent, capability)
        return intent, module

    def prepare_execution(self, effect_id, intent, run_id, layout, device):
        intent, module = self.bind_intent(intent, layout, device)
        resources = tuple(sorted({*device.shared_resources,
            f'{device.mode}:{device.device_id}:module:{module}',
            *(f'{device.mode}:{device.device_id}:{b.labware}:{b.well}' for b in layout.bindings)}))
        context = PlanContext(run_id, device.device_id, device.mode, device.configuration_revision,
                              layout.revision, device.calibration_revision, resources)
        return self.gateway.prepare_processing(effect_id, intent, context, layout.bindings)


class InstrumentExecutionRouterInteractor:
    def __init__(self, preparers, incubator=None):
        self.preparers = dict(preparers)
        self.incubator = incubator

    def select_preparer(self, intent, layout, device):
        preparer = self.preparers.get(intent.capability)
        if preparer is None:
            raise ValueError('PROCESSING_INSTRUMENT_UNAVAILABLE')
        if intent.capability == 'thermal_hold' and self.incubator is not None:
            labwares = {b.labware for b in layout.bindings if b.reference in intent.targets}
            choices = [cap for cap in device.processing_capabilities.get(intent.capability, {}).values()
                       if labwares and labwares <= set(cap['labware'])]
            if len(choices) == 1 and choices[0].get('instrument_kind') == 'incubator':
                return self.incubator
        return preparer

    def bind_intent(self, intent, layout, device, physical_positions=None):
        return self.select_preparer(intent, layout, device).bind_intent(intent, layout, device, physical_positions)

    def prepare_execution(self, effect_id, intent, run_id, layout, device):
        return self.select_preparer(intent, layout, device).prepare_execution(effect_id, intent, run_id, layout, device)
