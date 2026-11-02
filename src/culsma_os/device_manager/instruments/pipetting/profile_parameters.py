"""Portable pipetting settings. Vendor liquid-class names stay in drivers."""
from dataclasses import dataclass
from math import isfinite
from ..models import ModuleProfileError


@dataclass(frozen=True)
class PipettingParameters:
    aspiration_height_mm: float
    dispense_height_mm: float
    aspiration_flow_rate_uL_s: float | None = None
    dispense_flow_rate_uL_s: float | None = None

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is None and 'flow_rate' in name:
                continue
            if type(value) not in (int, float) or not isfinite(value) or value < 0 or ('flow_rate' in name and value == 0):
                raise ModuleProfileError('PROFILE_PIPETTING_PARAMETER_INVALID', (name,))

    @classmethod
    def from_parameters(cls, values):
        if set(values) - set(cls.__dataclass_fields__) or not {'aspiration_height_mm', 'dispense_height_mm'} <= set(values):
            raise ModuleProfileError('PROFILE_PIPETTING_PARAMETERS_INVALID')
        return cls(**values)
