"""Assemble the same device validation policies for planning and execution."""
from .centrifuge.interactors import CentrifugeExecutionPreparationInteractor, CentrifugeMethodBindingInteractor
from .execution import InstrumentExecutionRouterInteractor
from .incubator.interactors import IncubatorExecutionPreparationInteractor
from .pipetting.interactors import PipettingExecutionPreparationInteractor
from .magnet.interactors import MagnetExecutionPreparationInteractor
from .shaker.interactors import ShakerExecutionPreparationInteractor, VortexExecutionPreparationInteractor
from .temperature.interactors import TemperatureExecutionPreparationInteractor


class InstrumentPreparationFactory:
    """Share instrument construction across execution and offline preview."""

    @staticmethod
    def build_processing(gateway=None, motion=None):
        return InstrumentExecutionRouterInteractor({
            'magnetic_separation': MagnetExecutionPreparationInteractor(gateway, motion),
            'thermal_hold': TemperatureExecutionPreparationInteractor(gateway, motion),
            'orbital_shake': ShakerExecutionPreparationInteractor(gateway, motion),
            'vortex': VortexExecutionPreparationInteractor(gateway, motion),
            'centrifuge': CentrifugeExecutionPreparationInteractor(gateway, motion, CentrifugeMethodBindingInteractor()),
        }, {('thermal_hold', 'incubator'): IncubatorExecutionPreparationInteractor(gateway, motion)})

    @staticmethod
    def build_pipetting(gateway=None):
        return PipettingExecutionPreparationInteractor(gateway)
