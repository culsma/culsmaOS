"""Translate thermal and shaking program steps to resolved execution intents."""
from culsma.domains.agitation import AgitationMode, ShakeMotion
from culsma.pipeline.external_boundary import DEFAULT_EXTERNAL_PARAMETER_NORMALIZER
from .processing_arguments import ProcessingArgumentsInteractor
from .material_volumes import ProcessingMaterialVolumeInteractor
from culsma_os.device_manager.instruments.execution_models import ThermalHoldIntent, OrbitalShakeIntent, EnvironmentCondition


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
        if (not {"thermal", "duration"} <= set(env) or set(env) - {"thermal", "duration", "co2", "o2", "humidity"} or layer.get("env") != env
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
        return ThermalHoldIntent(step.step_id, self.arguments.physical_targets(pending, identities), temperature, duration,
            ProcessingMaterialVolumeInteractor().capture(pending.before_material_state, identities),
            self.environment_conditions(env))


    def environment_conditions(self, environment):
        conditions = []
        for name in ('co2', 'o2', 'humidity'):
            if name in environment:
                value = self.arguments.quantity(environment[name], {'%': 1})
                if not 0 <= value <= 100:
                    raise ValueError('PROCESSING_ENVIRONMENT_VALUE_INVALID')
                conditions.append(EnvironmentCondition(name, value, '%'))
        return tuple(conditions)


class OrbitalShakePreparationInteractor:
    def __init__(self, arguments=None):
        self.arguments = arguments or ProcessingArgumentsInteractor()

    def resolve_intent(self, pending):
        step = pending.prepared.runtime_step
        required = {"sample", "mode", "rate", "duration"}
        if (step.op != "agit"
                or set(step.gate or {}) - {"entry", "entry_kind", "entry_name", "env", "env_targets", "env_layers"}
                or not required <= set(step.args) <= required | {"motion"}):
            raise ValueError("PROCESSING_AGITATION_SCOPE_UNSUPPORTED")
        # Checkpoints contain JSON enum values. Rehydrate through the language's public contract.
        args = DEFAULT_EXTERNAL_PARAMETER_NORMALIZER.normalize_runtime_arguments("agit", step.args)
        explicit_motion = "motion" in args
        if args["mode"] is not AgitationMode.SHAKE or (explicit_motion and args["motion"] is not ShakeMotion.ORBITAL):
            raise ValueError("PROCESSING_AGITATION_MOTION_UNSUPPORTED")
        rate = self.arguments.quantity(args["rate"], {"rpm": 1})
        duration = self.arguments.quantity(args["duration"], {"s": 1, "min": 60, "h": 3600})
        if int(rate) != rate:
            raise ValueError("PROCESSING_AGITATION_RATE_UNSUPPORTED")
        if duration <= 0:
            raise ValueError("PROCESSING_DURATION_INVALID")
        proposal = pending.prepared.material_result
        if proposal is None or not proposal.ok or proposal.delta.get("op") != "agit":
            raise ValueError("PROCESSING_MATERIAL_PROPOSAL_INVALID")
        targets = self.arguments.targets(pending.before_material_state, [args["sample"]])
        conditions = self.environment_conditions(pending, targets, duration)
        return OrbitalShakeIntent(step.step_id, self.arguments.physical_targets(pending, targets), int(rate), duration, conditions,
            requires_motion_default=not explicit_motion)

    def environment_conditions(self, pending, targets, duration):
        """Preserve a single environment applied to this agitation's exact targets."""
        gate = pending.prepared.runtime_step.gate or {}
        if not any(key in gate for key in ('env', 'env_layers', 'env_targets')):
            return ()
        env, layers = gate.get('env', {}), gate.get('env_layers', [])
        if (len(layers) != 1 or layers[0].get('env') != env
                or layers[0].get('env_targets') != gate.get('env_targets')
                or not env or set(env) - {'thermal', 'duration', 'co2', 'o2', 'humidity'}):
            raise ValueError('PROCESSING_AGITATION_ENVIRONMENT_UNSUPPORTED')
        scoped = self.arguments.targets(pending.before_material_state, gate.get('env_targets', []))
        if set(scoped) != set(targets):
            raise ValueError('PROCESSING_AGITATION_ENVIRONMENT_TARGETS_MISMATCH')
        if 'duration' in env and self.arguments.quantity(env['duration'], {'s': 1, 'min': 60, 'h': 3600}) != duration:
            raise ValueError('PROCESSING_AGITATION_ENVIRONMENT_DURATION_MISMATCH')
        conditions = ThermalHoldPreparationInteractor(self.arguments).environment_conditions(env)
        if 'thermal' in env:
            temperature = self.arguments.quantity(env['thermal'], {'C': 1})
            conditions = (EnvironmentCondition('thermal', temperature, 'C'), *conditions)
        return conditions
