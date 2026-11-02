"""Prepare a pipetting profile selection; never dispatch a transfer."""
from ..interactors import ModuleProfileResolutionInteractor
from ..models import MethodResolutionRequest, ResolvedModuleMethod, ModuleProfileError


class PipettingProfileInteractor(ModuleProfileResolutionInteractor):
    def prepare_step_method(self, request: MethodResolutionRequest) -> ResolvedModuleMethod:
        """Prepare pipetting from an exact saved profile revision; do not execute devices."""
        if request.related_profiles:
            raise ModuleProfileError('PIPETTING_RELATED_PROFILE_UNSUPPORTED')
        profile = self.selection.load_and_validate_profile_revision(request, 'pipetting')
        result = self.methods.validate_and_select_step_method(request, profile, ())
        return self.selection.verify_selection_matches_request(request, profile, (), result)


class PipettingCapabilityInteractor:
    def require_supported(self, requirements, device):
        if any(r not in device.transfer_requirements for r in requirements):
            raise ValueError('TRANSFER_CONSTRAINT_UNSUPPORTED')

    def validate_intent(self, intent, device):
        self.require_supported(intent.requirements, device)
        if device.supports_transfer is False:
            raise ValueError('TRANSFER_DEVICE_UNSUPPORTED')
        kind = getattr(intent, 'selection_kind', None)
        if kind is not None and kind not in device.transfer_selection_capabilities:
            raise ValueError('DRIVER_TRANSFER_SELECTION_UNSUPPORTED')


class PipettingExecutionPreparationInteractor(PipettingCapabilityInteractor):
    def __init__(self, gateway):
        self.gateway = gateway

    def prepare_context(self, run_id, layout, device, expectations=()):
        from culsma_os.driver_framework.models import PlanContext
        resources = tuple(sorted((
            *device.shared_resources,
            *(f'{device.mode}:{device.device_id}:{b.labware}:{b.well}' for b in layout.bindings),
        )))
        return PlanContext(run_id, device.device_id, device.mode, device.configuration_revision,
                           layout.revision, device.calibration_revision, resources, tuple(expectations))

    def prepare_execution(self, effect_id, intent, context, bindings, completion_unit='operation'):
        return self.gateway.prepare(effect_id, intent, context, bindings, completion_unit=completion_unit)

    def prepare_group(self, effect_id, step_id, member_ids, intents, context, bindings):
        from .models import TransferGroupIntent
        from culsma_os.driver_framework.models import PreparedTransferGroup
        if not intents or len(intents) != len(member_ids):
            raise ValueError('TRANSFER_GROUP_EMPTY')
        if getattr(self.gateway, 'supports_collective_execution', False):
            return self.gateway.prepare_collective_group(effect_id, step_id, member_ids, intents, context, bindings)
        plans = tuple(self.prepare_execution(identity, intent, context, bindings, completion_unit='member')
                      for identity, intent in zip(member_ids, intents))
        requirements = {}
        for plan in plans:
            values = plan.description.get('resource_requirements')
            if not isinstance(values, dict) or any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in values.items()):
                raise ValueError('TRANSFER_GROUP_RESOURCE_REQUIREMENTS_INVALID')
            for resource, amount in values.items():
                requirements[resource] = requirements.get(resource, 0) + amount
        return PreparedTransferGroup(effect_id, TransferGroupIntent(step_id, tuple(p.intent for p in plans)),
            context, plans, {'resource_requirements': requirements, 'member_effect_ids': [p.effect_id for p in plans]})
