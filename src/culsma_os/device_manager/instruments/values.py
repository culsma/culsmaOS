"""JSON value isolation for saved execution profiles; no vendor interpretation."""
from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType



class ProfileValueInteractor:
    @staticmethod
    def freeze_value(value):
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is float and isfinite(value):
            return value
        if isinstance(value, Mapping) and all(type(key) is str for key in value):
            return MappingProxyType({key: ProfileValueInteractor.freeze_value(item) for key, item in value.items()})
        if isinstance(value, (tuple, list)):
            return tuple(ProfileValueInteractor.freeze_value(item) for item in value)
        raise ValueError('PROFILE_PARAMETER_VALUE_INVALID')


    @staticmethod
    def plain_value(value):
        if isinstance(value, Mapping):
            return {key: ProfileValueInteractor.plain_value(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [ProfileValueInteractor.plain_value(item) for item in value]
        return value


freeze_value = ProfileValueInteractor.freeze_value
plain_value = ProfileValueInteractor.plain_value
