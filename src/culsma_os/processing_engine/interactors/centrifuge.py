"""Language-to-OS centrifuge mapping, independent of any instrument or SDK."""
from culsma.domains.agitation import AgitationMode
from culsma.pipeline.external_boundary import DEFAULT_EXTERNAL_PARAMETER_NORMALIZER
from ..models import CentrifugeIntent, CentrifugeSeparationIntent, ProcessingMethodProfile
from .preparation import ProcessingArgumentsInteractor, OrbitalShakePreparationInteractor, MagneticPreparationInteractor


class CentrifugePreparationInteractor:
    def __init__(self, arguments=None):
        self.arguments = arguments or ProcessingArgumentsInteractor()

    def resolve_intent(self, pending):
        step = pending.prepared.runtime_step
        if (step.op != "agit"
                or set(step.gate or {}) - {"entry", "entry_kind", "entry_name"}
                or set(step.args) != {"sample", "mode", "drive", "duration"}):
            raise ValueError("PROCESSING_CENTRIFUGE_SCOPE_UNSUPPORTED")
        args = DEFAULT_EXTERNAL_PARAMETER_NORMALIZER.normalize_runtime_arguments("agit", step.args)
        if args["mode"] is not AgitationMode.CENTRIFUGE:
            raise ValueError("PROCESSING_CENTRIFUGE_MODE_UNSUPPORTED")
        drive = self.arguments.quantity(args["drive"], {"g": 1, "rpm": 1})
        duration = self.arguments.quantity(args["duration"], {"s": 1, "min": 60, "h": 3600})
        if drive <= 0 or duration <= 0:
            raise ValueError("PROCESSING_CENTRIFUGE_QUANTITY_INVALID")
        proposal = pending.prepared.material_result
        if proposal is None or not proposal.ok or proposal.delta.get("op") != "agit":
            raise ValueError("PROCESSING_MATERIAL_PROPOSAL_INVALID")
        targets = self.arguments.targets(pending.before_material_state, [args["sample"]])
        return CentrifugeIntent(step.step_id, targets, drive, args["drive"]["unit"], duration)


class AgitationPreparationInteractor:
    """Dispatch language agitation modes to injected capability planners."""
    def __init__(self, mode_planners=None):
        self.mode_planners = ({AgitationMode.SHAKE: OrbitalShakePreparationInteractor(),
                               AgitationMode.CENTRIFUGE: CentrifugePreparationInteractor()}
                              if mode_planners is None else dict(mode_planners))

    def resolve_intent(self, pending):
        step = pending.prepared.runtime_step
        if step.op != "agit":
            raise ValueError("PROCESSING_AGITATION_SCOPE_UNSUPPORTED")
        args = DEFAULT_EXTERNAL_PARAMETER_NORMALIZER.normalize_runtime_arguments("agit", step.args)
        planner = self.mode_planners.get(args.get("mode"))
        if planner is None:
            raise ValueError("PROCESSING_AGITATION_MOTION_UNSUPPORTED")
        return planner.resolve_intent(pending)


class CentrifugeSeparationPreparationInteractor:
    def __init__(self, arguments=None):
        self.arguments = arguments or ProcessingArgumentsInteractor()

    def resolve_intent(self, pending):
        from culsma.runtime.material.args import arg_call, call_arg_value
        step = pending.prepared.runtime_step
        if (step.op != "sep" or set(step.args) != {"sample", "program"}
                or set(step.gate or {}) - {"entry", "entry_kind", "entry_name"}):
            raise ValueError("PROCESSING_CENTRIFUGE_SEPARATION_SCOPE_UNSUPPORTED")
        program = arg_call(step.args["program"])
        if program is None or program.get("name") != "centrifuge_program":
            raise ValueError("PROCESSING_CENTRIFUGE_PROGRAM_UNSUPPORTED")
        entries = program.get("args", [])
        names = [a.get("name") for a in entries]
        if (set(names) - {"drive", "keep_source"} or "drive" not in names
                or len(names) != len(set(names))):
            raise ValueError("PROCESSING_CENTRIFUGE_PROGRAM_UNSUPPORTED")
        quantity = call_arg_value(program, "drive")
        drive = self.arguments.quantity(quantity, {"g": 1, "rpm": 1})
        if drive <= 0:
            raise ValueError("PROCESSING_CENTRIFUGE_QUANTITY_INVALID")
        targets = self.arguments.targets(pending.before_material_state, [step.args["sample"]])
        proposal = pending.prepared.material_result
        if (len(targets) != 1 or proposal is None or not proposal.ok
                or proposal.delta.get("op") != "sep" or proposal.delta.get("mode") != "contents_state"
                or proposal.delta.get("program_kind") != "centrifuge_program"
                or proposal.delta.get("source") != targets[0].container_id):
            raise ValueError("PROCESSING_CENTRIFUGE_PROPOSAL_UNSUPPORTED")
        return CentrifugeSeparationIntent(step.step_id, targets, drive, quantity["unit"])


class CentrifugeMethodBindingInteractor:
    def bind(self, intent, capability):
        from math import isfinite
        if isinstance(intent, CentrifugeIntent):
            return intent  # agit already contains its explicit language duration.
        if not isinstance(intent, CentrifugeSeparationIntent):
            raise ValueError("PROCESSING_METHOD_INTENT_UNSUPPORTED")
        profiles = capability.get("method_profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("PROCESSING_METHOD_PROFILE_INVALID")
        profile = profiles.get(intent.program_kind)
        if profile is None:
            raise ValueError("PROCESSING_METHOD_PROFILE_REQUIRED")
        if (not isinstance(profile, dict) or set(profile) != {"profile_id", "revision", "duration_seconds"}
                or any(not isinstance(profile.get(k), str) or not profile[k].strip()
                       for k in ("profile_id", "revision"))
                or type(profile["duration_seconds"]) not in {int, float}
                or not isfinite(profile["duration_seconds"]) or profile["duration_seconds"] <= 0):
            raise ValueError("PROCESSING_METHOD_PROFILE_INVALID")
        binding = ProcessingMethodProfile(profile["profile_id"], profile["revision"], float(profile["duration_seconds"]))
        return CentrifugeIntent(intent.step_id, intent.targets, intent.drive_value, intent.drive_unit,
                                binding.duration_seconds, binding, intent.program_kind)


class SeparationPreparationInteractor:
    def __init__(self, program_planners=None):
        self.program_planners = ({"magnetic_program": MagneticPreparationInteractor(),
            "centrifuge_program": CentrifugeSeparationPreparationInteractor()}
            if program_planners is None else dict(program_planners))

    def resolve_intent(self, pending):
        from culsma.runtime.material.args import arg_call
        step = pending.prepared.runtime_step
        program = arg_call(step.args.get("program"))
        planner = self.program_planners.get(program.get("name")) if program is not None else None
        if step.op != "sep" or planner is None:
            raise ValueError("PROCESSING_SEPARATION_PROGRAM_UNSUPPORTED")
        return planner.resolve_intent(pending)
