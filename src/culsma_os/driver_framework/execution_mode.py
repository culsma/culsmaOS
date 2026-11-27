"""OS-owned execution selection. Providers supply implementations, never choose one."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import StrEnum
import json


class ExecutionMode(StrEnum):
    SIMULATION = 'simulation'
    PHYSICAL = 'physical'


@dataclass(frozen=True)
class ExecutionSelection:
    mode: ExecutionMode
    simulator: str | None = None

    def __post_init__(self):
        if not isinstance(self.mode, ExecutionMode):
            raise ValueError('EXECUTION_MODE_ENUM_REQUIRED')
        if self.mode is ExecutionMode.SIMULATION:
            if not isinstance(self.simulator, str) or not self.simulator.strip():
                raise ValueError('SIMULATOR_SELECTION_REQUIRED')
        elif self.simulator is not None:
            raise ValueError('PHYSICAL_SIMULATOR_NOT_ALLOWED')

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict) or set(record) != {'mode', 'simulator'}:
            raise ValueError('EXECUTION_SELECTION_INVALID')
        return cls(ExecutionMode(record['mode']), record['simulator'])

    def as_record(self):
        return {'mode': self.mode.value, 'simulator': self.simulator}


class ExecutionImplementation(ABC):
    """One provider implementation bound to one mode; no fallback operation."""
    selection: ExecutionSelection
    label: str

    @abstractmethod
    def build(self, context): ...

    def describe(self):
        return {**self.selection.as_record(), 'label': self.label}


class SimulationExecutionImplementation(ExecutionImplementation):
    def __init__(self, simulator, label, builder):
        self.selection = ExecutionSelection(ExecutionMode.SIMULATION, simulator)
        self.label, self.builder = label, builder

    def build(self, context):
        return self.builder(context, self.selection)


class PhysicalExecutionImplementation(ExecutionImplementation):
    def __init__(self, label, builder):
        self.selection = ExecutionSelection(ExecutionMode.PHYSICAL)
        self.label, self.builder = label, builder

    def build(self, context):
        return self.builder(context, self.selection)


class ExecutionSelectionInteractor:
    def configuration(self, context):
        return json.loads(context.config_path.read_text()) if context.config_path else {}

    def implementations(self, factory):
        values = tuple(factory.execution_implementations())
        if (not values or any(not isinstance(v, ExecutionImplementation) for v in values)
                or len({v.selection for v in values}) != len(values)):
            raise ValueError('EXECUTION_IMPLEMENTATIONS_INVALID')
        return values

    def selection(self, factory, context, configuration=None):
        if context.execution_selection is not None:
            if not isinstance(context.execution_selection, ExecutionSelection):
                raise ValueError('EXECUTION_SELECTION_INVALID')
            return context.execution_selection
        configuration = self.configuration(context) if configuration is None else configuration
        record = configuration.get('execution_selection')
        if record is None:
            # A migration adapter reads old fields; selection still happens here in OS.
            record = factory.legacy_execution_selection(configuration)
        return ExecutionSelection.from_record(record)

    def select(self, factory, selection):
        matches = [v for v in self.implementations(factory) if v.selection == selection]
        if len(matches) != 1:
            raise ValueError('EXECUTION_IMPLEMENTATION_UNSUPPORTED')
        return matches[0]

    def build(self, factory, context):
        selection = self.selection(factory, context)
        implementation = self.select(factory, selection)
        result = implementation.build(replace(context, execution_selection=selection))
        port, snapshot, *_ = result
        if snapshot.mode != selection.mode:
            port.close()
            raise ValueError('EXECUTION_MODE_MISMATCH')
        return result

    def prepare_configuration(self, factory, configuration, selection):
        """Save the explicit choice using the provider's legacy-field migration adapter."""
        self.select(factory, selection)
        value = factory.configuration_for_execution(configuration, selection)
        return {**value, 'execution_selection': selection.as_record()}


def motion_state_database(station_database, mode, simulator=None):
    """Physical location records retain their existing store; simulation has its own."""
    from hashlib import sha256
    mode = ExecutionMode(mode)
    if mode is ExecutionMode.PHYSICAL:
        return station_database
    identity = sha256((simulator or 'legacy').encode()).hexdigest()[:12]
    return station_database.with_name('motion-simulation-' + identity + '.sqlite3')
