"""Mode changes select implementations without removing station inventory."""
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from culsma_os.driver_framework.execution_mode import (
    ExecutionMode, ExecutionSelection, ExecutionSelectionInteractor,
    SimulationExecutionImplementation, PhysicalExecutionImplementation)
from culsma_os.program_manager.models import HostBuildContext


class Provider:
    def __init__(self):
        self.calls = []
        self.port = SimpleNamespace(close=Mock())

    def execution_implementations(self):
        return (SimulationExecutionImplementation('vendor', 'Vendor simulator', self.build),
                SimulationExecutionImplementation('model', 'Local model', self.build),
                PhysicalExecutionImplementation('Hardware', self.build))

    def legacy_execution_selection(self, configuration):
        return {'mode': configuration['mode'], 'simulator': 'vendor' if configuration['mode']=='simulation' else None}

    def build(self, context, selection):
        self.calls.append((context, selection))
        return self.port, SimpleNamespace(mode=selection.mode, devices=('pipettor','incubator')), {}, {}, None

    def configuration_for_execution(self, configuration, selection):
        return {**configuration, 'mode': selection.mode.value}


@pytest.fixture
def context(tmp_path):
    path=tmp_path/'deck.json'
    path.write_text(json.dumps({'mode':'simulation', 'devices':['pipettor','incubator']}))
    return HostBuildContext(tmp_path/'station.db','test',path,tmp_path/'artifacts')


def test_one_station_keeps_inventory_across_all_implementations(context):
    factory=Provider(); owner=ExecutionSelectionInteractor()
    inventories=[]
    for selection in (ExecutionSelection(ExecutionMode.SIMULATION,'vendor'),
                      ExecutionSelection(ExecutionMode.SIMULATION,'model'),
                      ExecutionSelection(ExecutionMode.PHYSICAL)):
        selected=replace(context,execution_selection=selection)
        result=owner.build(factory,selected)
        inventories.append(result[1].devices)
        assert factory.calls[-1][0].execution_selection == selection
        assert result[1].mode is selection.mode
    assert len(set(inventories))==1
    assert json.loads(context.config_path.read_text())['mode']=='simulation'


def test_saved_choice_wins_over_legacy_configuration(context):
    value=json.loads(context.config_path.read_text())
    value['execution_selection']={'mode':'physical','simulator':None}
    context.config_path.write_text(json.dumps(value))
    factory=Provider(); ExecutionSelectionInteractor().build(factory,context)
    assert factory.calls[0][1].mode is ExecutionMode.PHYSICAL


def test_unsupported_choice_never_builds_or_falls_back(context):
    factory=Provider(); owner=ExecutionSelectionInteractor()
    with pytest.raises(ValueError,match='UNSUPPORTED'):
        owner.build(factory,replace(context,execution_selection=ExecutionSelection(ExecutionMode.SIMULATION,'missing')))
    assert not factory.calls


def test_failed_hardware_builder_never_tries_simulator(context):
    factory=Provider()
    factory.build=Mock(side_effect=RuntimeError('connection refused'))
    with pytest.raises(RuntimeError,match='connection refused'):
        ExecutionSelectionInteractor().build(factory,replace(context,execution_selection=ExecutionSelection(ExecutionMode.PHYSICAL)))
    assert factory.build.call_count==1


def test_wrong_returned_mode_closes_connection(context):
    factory=Provider()
    factory.build=Mock(return_value=(factory.port,SimpleNamespace(mode='simulation'),{},{},None))
    with pytest.raises(ValueError,match='MODE_MISMATCH'):
        ExecutionSelectionInteractor().build(factory,replace(context,execution_selection=ExecutionSelection(ExecutionMode.PHYSICAL)))
    factory.port.close.assert_called_once()


def test_save_choice_preserves_device_configuration(context):
    owner=ExecutionSelectionInteractor(); original=json.loads(context.config_path.read_text())
    result=owner.prepare_configuration(Provider(),original,ExecutionSelection(ExecutionMode.PHYSICAL))
    assert result['devices']==original['devices']
    assert original['mode']=='simulation'
    assert ExecutionSelection.from_record(result['execution_selection']).mode is ExecutionMode.PHYSICAL


@pytest.mark.parametrize('record', [None,{}, {'mode':'other','simulator':None},
    {'mode':'simulation','simulator':None}, {'mode':'physical','simulator':'vendor'},
    {'mode':'physical','simulator':None,'extra':True}])
def test_invalid_serialized_selections(record):
    with pytest.raises(ValueError): ExecutionSelection.from_record(record)


def test_internal_selection_requires_enum():
    with pytest.raises(ValueError,match='ENUM_REQUIRED'):
        ExecutionSelection('physical')


def test_duplicate_implementation_is_not_ambiguously_selected(context):
    factory=Provider(); one=factory.execution_implementations()[0]
    factory.execution_implementations=lambda:(one,one)
    with pytest.raises(ValueError,match='IMPLEMENTATIONS_INVALID'):
        ExecutionSelectionInteractor().build(factory,context)


def test_simulated_motion_has_separate_store_from_physical(context):
    from culsma_os.driver_framework.execution_mode import motion_state_database
    physical=motion_state_database(context.database_path,ExecutionMode.PHYSICAL)
    simulator=motion_state_database(context.database_path,ExecutionMode.SIMULATION,'vendor')
    model=motion_state_database(context.database_path,ExecutionMode.SIMULATION,'model')
    assert physical==context.database_path and len({physical,simulator,model})==3


@pytest.mark.parametrize('explicit', [True, False])
def test_inspection_reads_the_same_motion_store_as_execution(tmp_path, explicit):
    from culsma_os.bootstrap import OSApplicationFactory
    from culsma_os.driver_framework.execution_mode import motion_state_database
    from culsma_os.storage import DatabaseConnection
    from culsma_os.workspace_manager.repository import SqliteLabwarePositionRepository
    from tests.support.device_manager.device_inspection import InspectionFixture
    fixture = InspectionFixture(tmp_path)
    selection = ExecutionSelection(ExecutionMode.SIMULATION, 'vendor')
    context = replace(fixture.context, execution_selection=selection)
    if not explicit:
        path = tmp_path/'configuration.json'
        path.write_text(json.dumps({'execution_selection': selection.as_record()}))
        context = replace(context, execution_selection=None, config_path=path, driver_name='test')
    connection = DatabaseConnection(motion_state_database(fixture.station, selection.mode, selection.simulator)).open()
    try:
        repository = SqliteLabwarePositionRepository(connection)
        repository.initialize('test', 'r1', {'plate': 'module:heater'})
        inspector = OSApplicationFactory({'test': Provider()}).build_device_inspector(context)
        result = inspector.execute()['devices'][0]['positions']
        assert result['current'] == {'plate': 'module:heater'}
        assert result['scope'] == 'station'
        # Preparation reads the same store, not the previous shared station file.
        device = replace(fixture.device)
        catalogue = {'device_id':'test', 'configuration_revision':'r1'}
        from unittest.mock import patch
        with patch.object(type(device), 'verify_workspace_capabilities'):
            assert inspector.preparation_snapshot(catalogue, device)[1] == result['current']
        # A physical inspector must not observe the simulator's position.
        physical = OSApplicationFactory({}).build_device_inspector(replace(fixture.context,
            execution_selection=ExecutionSelection(ExecutionMode.PHYSICAL)))
        assert physical.execute()['devices'][0]['positions']['current'] == {'plate':'D1'}
    finally:
        connection.close()


def test_configuration_command_saves_choice_without_changing_devices(tmp_path,monkeypatch):
    from culsma_os.bootstrap import OSApplicationFactory
    from culsma_os.workspace_manager.models import StationConfigurationRequest
    from tests.support.workspace_manager.configuration import ConfigurationFixture
    factory=Provider()
    monkeypatch.setattr(OSApplicationFactory,'device_factory',lambda self,context:factory)
    fixture=ConfigurationFixture(tmp_path/'drafts.db')
    fixture.interactor.execution_factory=lambda driver:factory
    original={'mode':'simulation','devices':['pipettor','incubator'],'valid':True}
    draft=fixture.execute(StationConfigurationRequest('create',title='Station',driver='test-profile',configuration=original))['draft']
    options=fixture.execute(StationConfigurationRequest('execution_options',draft['draft_id'],1))
    assert len(options['implementations'])==3
    unchanged = fixture.execute(StationConfigurationRequest('select_execution',draft['draft_id'],1,
        configuration=options['selected']))['draft']
    assert unchanged == draft
    saved=fixture.execute(StationConfigurationRequest('select_execution',draft['draft_id'],1,
        configuration={'mode':'physical','simulator':None}))['draft']
    assert saved['revision']==2 and saved['configuration']['devices']==original['devices']
    assert saved['configuration']['mode']=='physical'
    assert fixture.repository.get(draft['draft_id'],1).as_dict()['configuration']==original
    assert not factory.calls  # Saving a choice must not connect or execute.
    with pytest.raises(ValueError,match='REVISION_CONFLICT'):
        fixture.execute(StationConfigurationRequest('select_execution',draft['draft_id'],1,
            configuration={'mode':'simulation','simulator':'model'}))


def test_mcp_mode_tool_uses_the_same_configuration_command():
    from culsma_os.console.adapters.settings_mcp import MCPSettingsTools
    tools=MCPSettingsTools();tools.raw_credential='test';tools.configuration=Mock()
    tools.select_execution_mode('draft',4,'physical')
    request=tools.configuration.execute.call_args.args[1]
    assert request.action=='select_execution' and request.revision==4
    assert request.configuration=={'mode':'physical','simulator':None}


def test_selection_parser_reads_legacy_and_explicit_context(context):
    owner=ExecutionSelectionInteractor();factory=Provider()
    assert owner.selection(factory,context)==ExecutionSelection(ExecutionMode.SIMULATION,'vendor')
    chosen=ExecutionSelection(ExecutionMode.PHYSICAL)
    assert owner.selection(factory,replace(context,execution_selection=chosen)) is chosen
    with pytest.raises(ValueError,match='INVALID'):
        owner.selection(factory,replace(context,execution_selection='physical'))
    implementation=owner.select(factory,chosen)
    assert implementation.describe()=={'mode':'physical','simulator':None,'label':'Hardware'}


def test_unsupported_selection_does_not_advance_configuration_revision(tmp_path,monkeypatch):
    from culsma_os.bootstrap import OSApplicationFactory
    from culsma_os.workspace_manager.models import ConfigurationError,StationConfigurationRequest
    from tests.support.workspace_manager.configuration import ConfigurationFixture
    monkeypatch.setattr(OSApplicationFactory,'device_factory',lambda self,context:Provider())
    fixture=ConfigurationFixture(tmp_path/'drafts.db')
    fixture.interactor.execution_factory=lambda driver:Provider()
    draft=fixture.execute(StationConfigurationRequest('create',title='Station',driver='test-profile',
        configuration={'mode':'simulation','valid':True}))['draft']
    with pytest.raises(ConfigurationError,match='UNSUPPORTED'):
        fixture.execute(StationConfigurationRequest('select_execution',draft['draft_id'],1,
            configuration={'mode':'simulation','simulator':'missing'}))
    assert fixture.repository.get(draft['draft_id']).revision==1
