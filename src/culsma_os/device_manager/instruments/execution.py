"""Prepare a device plan from a resolved operation and authoritative layout."""
from culsma_os.device_manager.models import DeviceConfigurationSnapshot
from culsma_os.driver_framework.models import PlanContext
from culsma_os.workspace_manager.models import ProcessingPlacementPort


class InstrumentExecutionPreparationInteractor:
    capability = None

    def __init__(self, gateway, placement: ProcessingPlacementPort | None = None, method_binding=None):
        self.gateway = gateway
        self.placement = placement
        self.method_binding = method_binding

    def validate_intent(self, intent, capability):
        from math import isfinite
        if intent.capability != self.capability:
            raise ValueError('PROCESSING_INSTRUMENT_INTENT_MISMATCH')
        if 'maximum_hold_seconds' in capability:
            limit = capability['maximum_hold_seconds']
            if type(limit) not in (int, float) or not isfinite(limit) or limit <= 0:
                raise ValueError('PROCESSING_DURATION_CAPABILITY_INVALID')
            duration = getattr(intent, 'duration_seconds', None)
            if type(duration) not in (int, float) or not isfinite(duration) or not 0 < duration <= limit:
                raise ValueError(f'PROCESSING_DURATION_UNSUPPORTED: The configured module accepts durations up to {limit:g} s.')
        self.validate_environment_conditions(intent, capability)

    def validate_environment_conditions(self, intent, capability):
        self.require_environment_conditions(getattr(intent, 'environment_conditions', ()),
                                            capability.get('environment_conditions', {}))

    @staticmethod
    def require_environment_conditions(conditions, advertised, prefix='PROCESSING'):
        from math import isfinite
        from .execution_models import EnvironmentCondition
        if not isinstance(conditions, tuple) or len({c.name for c in conditions if isinstance(c,EnvironmentCondition)}) != len(conditions):
            raise ValueError(f'{prefix}_ENVIRONMENT_CONDITION_INVALID')
        for condition in conditions:
            limits = advertised.get(condition.name) if isinstance(advertised,dict) else None
            if (not isinstance(condition,EnvironmentCondition) or type(condition.value) not in (int,float)
                    or not isfinite(condition.value) or not isinstance(limits,dict)
                    or set(limits) != {'unit','minimum','maximum'} or condition.unit != limits['unit']
                    or any(type(limits[k]) not in (int,float) or not isfinite(limits[k]) for k in ('minimum','maximum'))
                    or not limits['minimum'] <= condition.value <= limits['maximum']):
                raise ValueError(f'{prefix}_ENVIRONMENT_CONDITION_UNSUPPORTED')

    def select_module(self, intent, layout, device, physical_positions):
        available = device.processing_modules(intent)
        bindings = {b.reference: b for b in layout.bindings}
        if len(bindings) != len(layout.bindings) or not intent.targets or any(t not in bindings for t in intent.targets):
            raise ValueError('PROCESSING_TARGET_UNBOUND')
        labwares = {bindings[t].labware for t in intent.targets}
        if len(labwares) != 1:
            raise ValueError('PROCESSING_MODULE_SCOPE')
        labware = next(iter(labwares))
        modules = tuple(name for name, capability in available.items() if labware in capability['labware'])
        if not modules and device.instrument_drivers is not None:
            raise ValueError(f'PROCESSING_LABWARE_UNSUPPORTED: No available {intent.capability} module accepts {labware}.')
        if self.placement is not None:
            module = self.placement.select_module(labware, modules, physical_positions)
        elif len(modules) == 1:
            module = modules[0]
        else:
            raise ValueError('PROCESSING_MODULE_UNAVAILABLE')
        return bindings, labware, module, available[module]

    def bind_intent(self, intent, layout, device, physical_positions=None):
        selection = self.select_module(intent, layout, device, physical_positions)
        return self.bind_selected(intent, selection, physical_positions)

    def bind_selected(self, intent, selection, physical_positions):
        bindings, labware, module, capability = selection
        exposed_wells = self.exposed_wells(intent, bindings, labware, capability)
        if any(b.labware == labware and b.reference not in intent.targets
               and (exposed_wells is None or b.well in exposed_wells) for b in bindings.values()):
            raise ValueError('PROCESSING_COLLATERAL_EXPOSURE')
        if self.placement is not None:
            self.placement.require_module(labware, module, physical_positions)
        destination = capability.get('release_destination')
        if destination is not None and physical_positions is not None and destination in physical_positions.values():
            raise ValueError('PROCESSING_RELEASE_DESTINATION_OCCUPIED')
        return self.validate_method(intent, capability), module

    def validate_method(self, intent, capability):
        if self.method_binding is not None:
            intent = self.method_binding.bind(intent, capability)
        self.validate_intent(intent, capability)
        return intent

    def exposed_wells(self, intent, bindings, labware, capability):
        """Resolve a separately removable holder; default to whole-labware exposure."""
        groups = capability.get('exposure_groups', {}).get(labware)
        if groups is None:
            return None
        targets = {bindings[target].well for target in intent.targets}
        if len(targets) != len(intent.targets) or not any(targets == set(group) for group in groups):
            raise ValueError('PROCESSING_MODULE_SCOPE')
        return targets

    def prepare_execution(self, effect_id, intent, run_id, layout, device):
        intent, module = self.bind_intent(intent, layout, device)
        return self.prepare_bound_execution(effect_id, intent, module, run_id, layout, device)

    def prepare_bound_execution(self, effect_id, intent, module, run_id, layout, device):
        resources = tuple(sorted({*device.shared_resources,
            f'{device.mode}:{device.device_id}:module:{module}',
            *(f'{device.mode}:{device.device_id}:{b.labware}:{b.well}' for b in layout.bindings)}))
        context = PlanContext(run_id, device.device_id, device.mode, device.configuration_revision,
                              layout.revision, device.calibration_revision, resources)
        return self.gateway.prepare_processing(effect_id, intent, context, layout.bindings)


class InstrumentExecutionRouterInteractor:
    def __init__(self, preparers, preparers_by_kind=None):
        self.preparers = dict(preparers)
        self.preparers_by_kind = dict(preparers_by_kind or {})

    def preparer_for(self, operation, capability):
        return self.preparers_by_kind.get((operation, capability.get('instrument_kind')), self.preparers[operation])

    def compatible_labware(self, intent, modules):
        """Narrow placement to modules that can honor the operation parameters."""
        compatible = set()
        matching = DeviceConfigurationSnapshot.matching_instruments(modules, getattr(intent, 'instrument_kind', None))
        candidates = DeviceConfigurationSnapshot.connected_candidates(matching).values()
        for capability in candidates:
            preparer = self.preparer_for(intent.capability, capability)
            try:
                preparer.validate_method(intent, capability)
            except ValueError:
                continue
            compatible.update(capability['labware'])
        # If no module accepts the parameters, prefer an otherwise compatible
        # location so preflight can report the actual parameter rejection.
        return compatible or {labware for capability in candidates for labware in capability['labware']}

    def select(self, intent, layout, device, physical_positions=None):
        preparer = self.preparers.get(intent.capability)
        if preparer is None:
            raise ValueError('PROCESSING_INSTRUMENT_UNAVAILABLE')
        selection = preparer.select_module(intent, layout, device, physical_positions)
        return self.preparer_for(intent.capability, selection[3]), selection

    def bind_intent(self, intent, layout, device, physical_positions=None):
        preparer, selection = self.select(intent, layout, device, physical_positions)
        return preparer.bind_selected(intent, selection, physical_positions)

    def prepare_execution(self, effect_id, intent, run_id, layout, device):
        preparer, selection = self.select(intent, layout, device)
        bound, module = preparer.bind_selected(intent, selection, None)
        return preparer.prepare_bound_execution(effect_id, bound, module, run_id, layout, device)
