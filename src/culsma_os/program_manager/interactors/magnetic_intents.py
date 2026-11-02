"""Map existing magnetic language steps; no hardware selection or dispatch."""
from .processing_arguments import ProcessingArgumentsInteractor
from culsma_os.device_manager.instruments.magnet.models import MagneticSeparationIntent


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
