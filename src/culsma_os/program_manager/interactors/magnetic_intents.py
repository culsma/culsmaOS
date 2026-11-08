"""Map existing magnetic language steps; no hardware selection or dispatch."""
from culsma.runtime.material.args import arg_string
from .processing_arguments import ProcessingArgumentsInteractor
from culsma_os.device_manager.instruments.magnet.models import MagneticSeparationIntent


class MagneticEnvironmentInteractor:
    def retains(self, pending):
        members = getattr(pending, 'members', (pending,))
        retained = [self.requires_field(member) for member in members]
        if any(retained) and not all(retained):
            raise ValueError('PROCESSING_CONDITION_MIXED_SCOPE_GROUP')
        return any(retained)

    @staticmethod
    def scope_ids(step):
        return {scope['scope_id'] for scope in (step.gate or {}).get('separation_scopes', [])
                if scope.get('program', {}).get('name') == 'magnetic_program'}

    @staticmethod
    def has_outer_field(step):
        gate = step.gate or {}
        layers = gate.get('env_layers', [{'env': gate.get('env', {})}])
        return any(arg_string(layer.get('env', {}).get('field')) == 'magnetic_rack' for layer in layers)

    @classmethod
    def ends_field_scope(cls, step):
        # Ending a sep guarantee must not remove a field still required by ENV.
        return (not cls.has_outer_field(step)
                and bool(cls.scope_ids(step) & set((step.gate or {}).get('separation_scope_ends', []))))

    @classmethod
    def starts_field_scope(cls, pending):
        return any(not cls.has_outer_field(member.prepared.runtime_step)
                   and (member.prepared.runtime_step.gate or {}).get('separation_entry')
                   in cls.scope_ids(member.prepared.runtime_step)
                   for member in getattr(pending, 'members', (pending,)))

    def requires_field(self, pending):
        if self.scope_ids(pending.prepared.runtime_step):
            return True
        if arg_string((pending.prepared.runtime_step.gate or {}).get('env', {}).get('field')) == 'magnetic_rack':
            return True
        proposal = pending.prepared.material_result
        if proposal is None or not pending.in_place_outputs:
            return False
        return any(pending.in_place_outputs.get(source.get("source"), (None, None, None))[2] == "1"
                   for source in proposal.delta.get("sources", ()))

    def validate(self, step, state, targets):
        gate = step.gate or {}
        env = gate.get("env", {})
        layers = gate.get("env_layers", [])
        allowed = {"protocol_name", "separation_scopes", "separation_entry", "separation_scope_ends", "entry", "entry_kind", "entry_name", "runtime_conditions", "env", "env_layers", "env_targets"}
        if step.op == "Mutation":
            allowed.add("constraint")
        if self.scope_ids(step):
            if len(self.scope_ids(step)) > 1:
                raise ValueError("PROCESSING_MAGNETIC_NESTED_SCOPE_UNSUPPORTED")
            if set(gate) - allowed:
                raise ValueError("PROCESSING_MAGNETIC_ENVIRONMENT_UNSUPPORTED")
            if any(set(layer.get("env", {})) != {"field"}
                   or arg_string(layer['env']['field']) != 'magnetic_rack' for layer in layers):
                raise ValueError("PROCESSING_MAGNETIC_ENVIRONMENT_UNSUPPORTED")
            candidates = [scope for scope in gate['separation_scopes']
                          if scope['scope_id'] in self.scope_ids(step)]
            for scope in reversed(candidates):
                exposed = ProcessingArgumentsInteractor().targets(state, [scope['sample']])
                if set(exposed) == set(targets):
                    return
            raise ValueError("PROCESSING_MAGNETIC_ENVIRONMENT_TARGETS")
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
        if step.op != "sep":
            raise ValueError("PROCESSING_MAGNETIC_SCOPE_UNSUPPORTED")
        program = arg_call(step.args.get("program"))
        if program is None or program.get("name") != "magnetic_program":
            raise ValueError("PROCESSING_MAGNETIC_PROGRAM_UNSUPPORTED")
        arguments = program.get("args", [])
        parameters = {argument.get("name"): argument.get("value") for argument in arguments}
        if (len(parameters) != len(arguments) or "duration" not in parameters
                or set(parameters) - {"duration", "device"}
                or ("device" in parameters and arg_string(parameters["device"]) != "magnetic_rack")):
            raise ValueError("PROCESSING_MAGNETIC_PROGRAM_UNSUPPORTED")
        duration = ProcessingArgumentsInteractor().quantity(parameters["duration"], {"s": 1, "min": 60, "h": 3600})
        if duration <= 0:
            raise ValueError("PROCESSING_DURATION_INVALID")
        targets = ProcessingArgumentsInteractor().targets(pending.before_material_state, [step.args["sample"]])
        if len(targets) != 1:
            raise ValueError("PROCESSING_MAGNETIC_SCOPE_UNSUPPORTED")
        if (proposal is None or not proposal.ok or proposal.delta.get("op") != "sep"
                or proposal.delta.get("program_kind") != "magnetic_program"
                or proposal.delta.get("source") != targets[0].container_id):
            raise ValueError("PROCESSING_MATERIAL_PROPOSAL_INVALID")
        named = proposal.delta.get("slots")
        if proposal.delta.get("mode") != "contents_state" and (not named or set(named) != {"0", "1"}):
            raise ValueError("PROCESSING_MATERIAL_PROPOSAL_INVALID")
        if not named or any(k in (step.gate or {}) for k in ("env", "env_layers", "env_targets")):
            MagneticEnvironmentInteractor().validate(step, pending.before_material_state, targets)
        physical = ProcessingArgumentsInteractor().physical_targets(pending, targets)
        return MagneticSeparationIntent(step.step_id, physical, duration)
