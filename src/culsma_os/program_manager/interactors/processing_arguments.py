"""Read public language values and resolved material references for OS requests."""
from math import isfinite
from culsma.runtime.material.refs import MaterialRefResolver
from culsma.runtime.values import RuntimeValueResolver
from culsma_os.workspace_manager.models import ResolvedContainerRef


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
