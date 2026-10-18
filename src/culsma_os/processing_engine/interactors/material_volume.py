"""Capture model-owned liquid volumes without claiming sensor measurements."""

from math import isfinite
from ..models import ProcessingMaterialVolume


class ProcessingMaterialVolumeInteractor:
    def capture(self, state, targets):
        containers = state.get("containers", {})
        return tuple(ProcessingMaterialVolume(target, self.known_volume(containers.get(target.container_id, {})))
                     for target in targets)

    def known_volume(self, container):
        volume = container.get("volume_uL")
        if type(volume) not in {int, float} or not isfinite(volume) or volume < 0:
            return None
        quantities = container.get("component_quantities", {})
        if not isinstance(quantities, dict):
            return None
        for quantity in quantities.values():
            if not isinstance(quantity, dict):
                return None
            dimension = quantity.get("dimension")
            if dimension == "volume" and (quantity.get("status") == "unknown"
                    or type(quantity.get("value")) not in {int, float}
                    or not isfinite(quantity["value"]) or quantity["value"] < 0):
                return None
            if dimension == "mass" and (quantity.get("status") == "unknown" or quantity.get("value") != 0):
                return None
        return float(volume)
