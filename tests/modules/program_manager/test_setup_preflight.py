"""Real Hamilton configuration, real compiler and isolated SQLite; no device mocks."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.device_manager.instruments.providers import InstrumentPreparationFactory
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.codec import RuntimeCheckpointCodecInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.setup_requirements import SetupRequirementsInteractor
from culsma_os.program_manager.interactors.setup_preflight import SetupProgramPreflightInteractor, PreparationIssueInteractor
from culsma_os.program_manager.providers import ProgramPreviewScopeFactory
from culsma_os.workspace_manager.interactors import WorkspacePlanningInteractor


def prepare(tmp_path, suffix=''):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    root = Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    data = json.loads((root/'examples/os-transfer-input/setup.json').read_text())
    config = tmp_path/'configuration.json'
    config.write_text(json.dumps({'schema':'culsma_hamilton_device_v1', 'device_id':'preview-test',
        'mode':'simulation', 'layout':data['layout'], 'execution':data['execution'],
        'bindings':{}, 'well_positions':{}, 'agent':{}}))
    source = tmp_path/'transfer.culs'
    source.write_text((root/'examples/os-transfer-input/transfer.culs').read_text() + suffix)
    compiled = CompilationInteractor().compile([source])
    factory = pytest.importorskip('culsma_hamilton_os.providers').HamiltonOSDeviceFactory()
    catalogue = factory.build_workspace_reader().execute(config)
    checkpoint = HostedRuntimeInteractor().create(compiled.plan, compiled.state, 'preview')
    requirements = SetupRequirementsInteractor(RuntimeCheckpointCodecInteractor()).inspect(checkpoint)
    loading = WorkspacePlanningInteractor().plan(requirements, catalogue)
    context = HostBuildContext(tmp_path/'os.sqlite3', 'hamilton-agent', config, tmp_path/'artifacts', station_root=tmp_path/'stations')
    devices = OSApplicationFactory().build_device_inspector(context)
    check = SetupProgramPreflightInteractor(devices, ProgramPreviewScopeFactory(), factory.build_configuration_snapshot_reader(), config)
    return check, compiled, catalogue, loading, config


def test_fresh_station_preview_projects_real_transfer_without_creating_persistent_state(tmp_path):
    check, compiled, catalogue, loading, config = prepare(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    state = RuntimeCheckpointCodecInteractor().dumps(compiled.state)
    result = check.inspect(compiled, catalogue, loading)
    assert result['status'] == 'passed', result
    assert result['checked_effects'] == 2
    assert result['projected_path_complete']
    assert RuntimeCheckpointCodecInteractor().dumps(compiled.state) == state
    assert {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('suffix,code', [
    ('\nagit(sample=source,mode=shake,motion=orbital,rate=500rpm,duration=1s);', 'INSTRUMENT_DEVICE_NOT_CONFIGURED'),
    ('\nwith env(thermal=37C,co2=5%,duration=3h){hold(sample=source);}', 'INSTRUMENT_DEVICE_NOT_CONFIGURED'),
    ('\nagit(sample=source,mode=vortex,duration=3s);', 'INSTRUMENT_DRIVER_UNAVAILABLE'),
])
def test_allocation_success_does_not_hide_unsupported_device_steps(tmp_path, suffix, code):
    check, compiled, catalogue, loading, config = prepare(tmp_path, suffix)
    assert loading['bindings']
    result = check.inspect(compiled, catalogue, loading)
    assert result['status'] == 'rejected', result
    assert result['checked_effects'] == 3
    issue = next(i for i in result['issues'] if i['code'] == code)
    assert issue['node_id'] and issue['span']
    assert issue['summary'] and issue['action']


def test_catalogue_and_configuration_revision_must_match(tmp_path):
    check, compiled, catalogue, loading, config = prepare(tmp_path)
    catalogue = deepcopy(catalogue)
    catalogue['configuration_revision'] = 'stale'
    result = check.inspect(compiled, catalogue, loading)
    assert result['status'] == 'rejected' and result['checked_effects'] == 0
    assert result['issues'][0]['code'] == 'SETUP_DEVICE_SNAPSHOT_UNAVAILABLE'


def test_unknown_diagnostics_remain_visible_without_invented_repair():
    issue = PreparationIssueInteractor().describe([{'code':'PREFLIGHT_OPERATION_REJECTED', 'message':'FUTURE_DRIVER_CODE', 'node_id':'entry.s8'}])[0]
    assert issue['code'] == issue['detail'] == 'FUTURE_DRIVER_CODE'
    assert issue['node_id'] == 'entry.s8'


@pytest.mark.parametrize('drive,expected', [('500g', 'passed'), ('12000g', 'rejected')])
def test_hamilton_loading_selects_the_bound_plate_and_checks_advertised_drive(tmp_path, drive, expected):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    root = Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    data = json.loads((root/'tools/local_console/fixtures/incubation/device.json').read_text())
    data['layout']['labware']['another_plate'] = {
        **data['layout']['labware']['destination_plate'], 'site': '2'}
    data['execution']['capacities_uL']['another_plate'] = 2000
    data['well_positions']['another_plate'] = data['well_positions']['destination_plate']
    data['bindings'] = {}
    data['processing'] = {'centrifuge': {
        'module_id': 'hig', 'labware': ['destination_plate'], 'adapter_id': '0',
        'acceleration_percent': 100, 'deceleration_percent': 100,
        'loading': 'declared_simulation_fixture',
    }}
    config = tmp_path/'configuration.json'
    config.write_text(json.dumps(data))
    source = tmp_path/'spin.culs'
    source.write_text(
        'let p=plate(label="Sample",format="96well",capacity=2000uL);\n'
        'let wells=p[A1];\n'
        f'agit(sample=wells[0],mode=centrifuge,drive={drive},duration=2s);\n')
    compiled = CompilationInteractor().compile([source])
    factory = pytest.importorskip('culsma_hamilton_os.providers').HamiltonOSDeviceFactory()
    catalogue = factory.build_workspace_reader().execute(config)
    checkpoint = HostedRuntimeInteractor().create(compiled.plan, compiled.state, 'preview')
    requirements = SetupRequirementsInteractor(RuntimeCheckpointCodecInteractor(), InstrumentPreparationFactory.build_processing())
    planner = WorkspacePlanningInteractor()
    plain = requirements.inspect(checkpoint)
    preferences = {'preferred': {plain[0]['allocation_id']: {'labware': 'another_plate', 'well': 'A1'}}}
    assert next(iter(planner.plan(plain, catalogue, preferences)['bindings'].values()))['labware'] == 'another_plate'
    demands = requirements.inspect(checkpoint, processing_capabilities=catalogue['processing_capabilities'])
    loading = planner.plan(demands, catalogue, preferences)
    assert next(iter(loading['bindings'].values()))['labware'] == 'destination_plate'
    context = HostBuildContext(tmp_path/'os.sqlite3', 'hamilton-agent', config, tmp_path/'artifacts', station_root=tmp_path/'stations')
    devices = OSApplicationFactory().build_device_inspector(context)
    check = SetupProgramPreflightInteractor(devices, ProgramPreviewScopeFactory(), factory.build_configuration_snapshot_reader(), config)
    result = check.inspect(compiled, catalogue, loading)
    assert result['status'] == expected, result
    if expected == 'rejected':
        issue, = result['issues']
        assert issue['code'] == 'PROCESSING_CENTRIFUGE_DRIVE_UNSUPPORTED'
        assert '12000 g' in issue['detail'] and '5000 g' in issue['detail']
