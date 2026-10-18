"""Map language-owned values to capability requests, then prepare a common device plan."""
from math import isfinite
from .material_volume import ProcessingMaterialVolumeInteractor
from culsma.domains.agitation import AgitationMode, ShakeMotion
from culsma.pipeline.external_boundary import DEFAULT_EXTERNAL_PARAMETER_NORMALIZER
from culsma.runtime.material.refs import MaterialRefResolver
from culsma.runtime.values import RuntimeValueResolver
from culsma_os.workspace_manager.models import ResolvedContainerRef, WorkspaceAccessPort, ProcessingPlacementPort
from culsma_os.device_manager.models import DeviceAccessPort
from culsma_os.driver_framework.models import PlanContext, DriverGatewayPort
from ..models import ThermalHoldIntent, OrbitalShakeIntent, ProcessingIntentPort, ProcessingIntentBindingPort


class ProcessingArgumentsInteractor:
    def quantity(self, value, units):
        if (not isinstance(value, dict) or value.get("kind") != "IRQuantity"
                or value.get("unit") not in units or type(value.get("value")) not in {int, float}
                or not isfinite(value["value"])):
            raise ValueError("PROCESSING_QUANTITY_UNSUPPORTED")
        result = float(value["value"]) * units[value["unit"]]
        if not isfinite(result):
            raise ValueError("PROCESSING_QUANTITY_UNSUPPORTED")
        return result


    def targets(self, state, expressions):
        identities = []
        for target in expressions:
            group = RuntimeValueResolver().resolve_runtime_ref_group(state, target)
            references = ([item["resolved_sample"] for item in group] if group is not None
                          else [MaterialRefResolver.resolve_target_ref(state, target)])
            if not references or any(identity is None for identity in references):
                raise ValueError("PROCESSING_TARGET_UNRESOLVED")
            identities.extend(references)
        if not identities or len(set(identities)) != len(identities):
            raise ValueError("PROCESSING_TARGET_INVALID")
        return tuple(ResolvedContainerRef(identity) for identity in identities)


class ThermalHoldPreparationInteractor:
    def __init__(self, arguments=None):
        self.arguments = arguments or ProcessingArgumentsInteractor()

    def resolve_intent(self, pending):
        step = pending.prepared.runtime_step
        gate = step.gate or {}
        if (step.op != "env_hold" or step.args
                or set(gate) - {"env", "env_targets", "env_layers", "entry", "entry_kind", "entry_name"}
                or len(gate.get("env_layers", [])) != 1):
            raise ValueError("PROCESSING_SCOPE_UNSUPPORTED")
        env = gate.get("env", {})
        layer = gate["env_layers"][0]
        if (set(env) != {"thermal", "duration"} or layer.get("env") != env
                or layer.get("env_targets") != gate.get("env_targets")):
            raise ValueError("PROCESSING_ENVIRONMENT_UNSUPPORTED")
        temperature = self.arguments.quantity(env["thermal"], {"C": 1})
        duration = self.arguments.quantity(env["duration"], {"s": 1, "min": 60, "h": 3600})
        if duration <= 0:
            raise ValueError("PROCESSING_DURATION_INVALID")
        if int(temperature) != temperature:
            raise ValueError("PROCESSING_TEMPERATURE_UNSUPPORTED")
        identities = self.arguments.targets(pending.before_material_state, gate.get("env_targets", []))
        proposal = pending.prepared.material_result
        if proposal is None or not proposal.ok:
            raise ValueError("PROCESSING_MATERIAL_PROPOSAL_INVALID")
        return ThermalHoldIntent(step.step_id, identities, temperature, duration,
            ProcessingMaterialVolumeInteractor().capture(pending.before_material_state, identities))


class OrbitalShakePreparationInteractor:
    def __init__(self, arguments=None):
        self.arguments = arguments or ProcessingArgumentsInteractor()

    def resolve_intent(self, pending):
        step = pending.prepared.runtime_step
        if (step.op != "agit"
                or set(step.gate or {}) - {"entry", "entry_kind", "entry_name"}
                or set(step.args) != {"sample", "mode", "motion", "rate", "duration"}):
            raise ValueError("PROCESSING_AGITATION_SCOPE_UNSUPPORTED")
        # Checkpoints contain JSON enum values. Rehydrate through the language's public contract.
        args = DEFAULT_EXTERNAL_PARAMETER_NORMALIZER.normalize_runtime_arguments("agit", step.args)
        if args["mode"] is not AgitationMode.SHAKE or args["motion"] is not ShakeMotion.ORBITAL:
            raise ValueError("PROCESSING_AGITATION_MOTION_UNSUPPORTED")
        rate = self.arguments.quantity(args["rate"], {"rpm": 1})
        duration = self.arguments.quantity(args["duration"], {"s": 1, "min": 60, "h": 3600})
        if not 200 <= rate <= 3000 or int(rate) != rate:
            raise ValueError("PROCESSING_AGITATION_RATE_UNSUPPORTED")
        if duration <= 0:
            raise ValueError("PROCESSING_DURATION_INVALID")
        proposal = pending.prepared.material_result
        if proposal is None or not proposal.ok or proposal.delta.get("op") != "agit":
            raise ValueError("PROCESSING_MATERIAL_PROPOSAL_INVALID")
        targets = self.arguments.targets(pending.before_material_state, [args["sample"]])
        return OrbitalShakeIntent(step.step_id, targets, int(rate), duration)


class ProcessingInteractor:
    def __init__(self, space: WorkspaceAccessPort, device: DeviceAccessPort,
                 gateway: DriverGatewayPort, device_id: str, intent_planners: dict[str, ProcessingIntentPort] | None = None, intent_bindings: dict[str, ProcessingIntentBindingPort] | None = None, placement: ProcessingPlacementPort | None = None):
        self.space, self.device, self.gateway, self.device_id = space, device, gateway, device_id
        self.intent_bindings = dict(intent_bindings or {})
        self.placement = placement
        self.intent_planners = ({"env_hold": ThermalHoldPreparationInteractor()}
                                if intent_planners is None else dict(intent_planners))

    def resolve_intent(self, pending):
        planner = self.intent_planners.get(pending.prepared.runtime_step.op)
        if planner is None:
            raise ValueError("PROCESSING_OPERATION_UNSUPPORTED")
        return planner.resolve_intent(pending)

    def prepare(self, request):
        pending = request.pending
        intent = self.resolve_intent(pending)
        layout = self.space.bind(request.run_id, pending.before_material_state, request.allocation_steps)
        device = self.device.get(self.device_id)
        intent, module = self.bind_intent(intent, layout, device)
        resources = tuple(sorted({*device.shared_resources,
            f"{device.mode}:{device.device_id}:module:{module}",
            *(f"{device.mode}:{device.device_id}:{b.labware}:{b.well}" for b in layout.bindings)}))
        context = PlanContext(request.run_id, device.device_id, device.mode, device.configuration_revision,
                              layout.revision, device.calibration_revision, resources)
        return self.gateway.prepare_processing(pending.effect_id, intent, context, layout.bindings)

    def preflight(self, pending, space, device, scope_id, allocation_steps, physical_positions=None):
        intent = self.resolve_intent(pending)
        layout = space.preview(scope_id, pending.before_material_state, allocation_steps)
        return self.bind_intent(intent, layout, device, physical_positions)[0]

    def bind_intent(self, intent, layout, device, physical_positions=None):
        bindings = {b.reference: b for b in layout.bindings}
        labwares = {bindings[t].labware for t in intent.targets}
        if len(labwares) != 1:
            raise ValueError("PROCESSING_MODULE_SCOPE")
        labware = next(iter(labwares))
        modules = [name for name, capability in device.processing_capabilities.get(intent.capability, {}).items()
                   if labware in capability["labware"]]
        if self.placement is not None:
            module = self.placement.select_module(labware, tuple(modules), physical_positions)
        elif len(modules) == 1:
            module = modules[0]
        else:
            raise ValueError("PROCESSING_MODULE_UNAVAILABLE")
        if any(b.labware == labware and b.reference not in intent.targets for b in layout.bindings):
            raise ValueError("PROCESSING_COLLATERAL_EXPOSURE")
        if self.placement is not None:
            self.placement.require_module(labware, module, physical_positions)
        capability = device.processing_capabilities[intent.capability][module]
        destination = capability.get("release_destination")
        if destination is not None and physical_positions is not None and destination in physical_positions.values():
            raise ValueError("PROCESSING_RELEASE_DESTINATION_OCCUPIED")
        if isinstance(intent, ThermalHoldIntent):
            self.validate_temperature(intent, capability)
        binder = self.intent_bindings.get(intent.capability)
        if binder is not None:
            intent = binder.bind(intent, device.processing_capabilities[intent.capability][module])
        return intent, module


    def validate_temperature(self, intent, capability):
        limits = capability.get("temperature_range_celsius", [4, 95])
        if (not isinstance(limits, (list, tuple)) or len(limits) != 2
                or any(type(v) not in {int, float} or not isfinite(v) for v in limits)
                or limits[0] > limits[1]):
            raise ValueError("PROCESSING_TEMPERATURE_CAPABILITY_INVALID")
        if not limits[0] <= intent.temperature_celsius <= limits[1]:
            raise ValueError("PROCESSING_TEMPERATURE_UNSUPPORTED")


class MagneticEnvironmentInteractor:
    def retains(self, pending):
        from culsma.runtime.material.args import arg_string
        members = getattr(pending, 'members', (pending,))
        retained = [arg_string((member.prepared.runtime_step.gate or {}).get('env', {}).get('field'))
                    == 'magnetic_rack' for member in members]
        if any(retained) and not all(retained):
            raise ValueError('PROCESSING_CONDITION_MIXED_SCOPE_GROUP')
        return any(retained)

    def validate(self, step, state, targets):
        from culsma.runtime.material.args import arg_string
        gate = step.gate or {}
        env = gate.get("env", {})
        layers = gate.get("env_layers", [])
        allowed = {"entry", "entry_kind", "entry_name", "env", "env_layers", "env_targets"}
        if step.op == "Mutation":
            allowed.add("constraint")
        if (set(gate) - allowed
                or set(env) != {"field"} or arg_string(env["field"]) != "magnetic_rack"
                or len(layers) != 1 or layers[0].get("env") != env
                or layers[0].get("env_targets") != gate.get("env_targets")):
            raise ValueError("PROCESSING_MAGNETIC_ENVIRONMENT_UNSUPPORTED")
        exposed = ProcessingArgumentsInteractor().targets(state, gate.get("env_targets", []))
        if set(exposed) != set(targets):
            raise ValueError("PROCESSING_MAGNETIC_ENVIRONMENT_TARGETS")


class MagneticPreparationInteractor:
    def resolve_intent(self, pending):
        from culsma.runtime.material.args import arg_call
        from ..models import MagneticSeparationIntent
        step = pending.prepared.runtime_step
        proposal = pending.prepared.material_result
        if step.op != "sep" or set(step.args) != {"sample", "program"}:
            raise ValueError("PROCESSING_MAGNETIC_SCOPE_UNSUPPORTED")
        program = arg_call(step.args["program"])
        if program is None or program.get("name") != "magnetic_program":
            raise ValueError("PROCESSING_MAGNETIC_PROGRAM_UNSUPPORTED")
        arguments = program.get("args", [])
        if len(arguments) != 1 or arguments[0].get("name") != "duration":
            raise ValueError("PROCESSING_MAGNETIC_PROGRAM_UNSUPPORTED")
        duration = ProcessingArgumentsInteractor().quantity(arguments[0]["value"], {"s": 1, "min": 60, "h": 3600})
        if duration <= 0:
            raise ValueError("PROCESSING_DURATION_INVALID")
        targets = ProcessingArgumentsInteractor().targets(pending.before_material_state, [step.args["sample"]])
        if len(targets) != 1:
            raise ValueError("PROCESSING_MAGNETIC_SCOPE_UNSUPPORTED")
        MagneticEnvironmentInteractor().validate(step, pending.before_material_state, targets)
        if (proposal is None or not proposal.ok or proposal.delta.get("op") != "sep"
                or proposal.delta.get("mode") != "contents_state" or proposal.delta.get("program_kind") != "magnetic_program"
                or proposal.delta.get("source") != targets[0].container_id):
            raise ValueError("PROCESSING_MATERIAL_PROPOSAL_INVALID")
        return MagneticSeparationIntent(step.step_id, targets, duration)
