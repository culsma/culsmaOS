"""OS and standalone providers coexist without discovery-order preferences."""
from pathlib import Path
from unittest.mock import Mock
import importlib.metadata
import pytest
from culsma.driver.models import ProgramExecutionRequest, ProgramExecutionError
from culsma.driver.interactors import ProgramExecutionInteractor
from culsma_os.bootstrap import OSApplicationFactory, OpentronsProgramExecutorFactory
from culsma_os.program_manager.interactors.language_entry import LanguageProgramInteractor


@pytest.mark.parametrize('bound,requested,expected', [
    ('opentrons-simulator','os-opentrons-simulator','opentrons-simulator'),
    (None,'hamilton-agent','hamilton-agent'),
])
def test_language_adapter_preserves_request_and_maps_only_explicit_device_binding(bound, requested, expected):
    runner = Mock()
    request = ProgramExecutionRequest((Path('protocol.culs'),),requested,Path('deck.json'),Path('out'))
    adapter = LanguageProgramInteractor(runner, device_driver_name=bound)
    adapter.execute(request)
    forwarded = runner.execute.call_args.args[0]
    assert forwarded.driver_name == expected
    assert forwarded.driver_config_path == request.config_path
    assert forwarded.host_database_path == Path('out/culsma-os.sqlite3')
    assert request.driver_name == requested


def test_os_factory_builds_explicit_device_binding(monkeypatch):
    runner = Mock()
    monkeypatch.setattr(OSApplicationFactory,'build_program_runner',lambda self: runner)
    adapter = OpentronsProgramExecutorFactory().build()
    assert adapter.runner is runner and adapter.device_driver_name == 'opentrons-simulator'


def test_installed_provider_names_resolve_to_distinct_owners():
    pytest.importorskip('culsma_opentrons.standalone')
    registry = importlib.metadata.entry_points(group='culsma.program_executors')
    expected = {
        'opentrons-simulator':'culsma_opentrons.standalone:StandaloneProgramExecutorFactory',
        'os-opentrons-simulator':'culsma_os.bootstrap:OpentronsProgramExecutorFactory',
    }
    for name, value in expected.items():
        entries = list(registry.select(name=name))
        assert len(entries) == 1 and entries[0].value == value
        assert callable(ProgramExecutionInteractor().load_executor(name).execute)


def test_true_duplicate_still_rejected_before_loading(monkeypatch):
    import culsma.driver.interactors as discovery
    entries = [Mock(),Mock()]
    monkeypatch.setattr(discovery,'entry_points',lambda **kwargs: entries)
    with pytest.raises(ProgramExecutionError,match='PROGRAM_EXECUTOR_NAME_CONFLICT'):
        ProgramExecutionInteractor().load_executor('opentrons-simulator')
    for entry in entries:
        entry.load.assert_not_called()
