"""Settings adapters delegate only; authentication remains in fixed business entries."""
import ast
import inspect
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.workspace_manager.interactors import StationConfigurationInteractor,ProgramBindingInteractor,LabwareConfigurationInteractor
from culsma_os.lifecycle_manager.interactors import ConsoleActivationInteractor,StationSelectionInteractor
from culsma_os.developer_tools.interactors import DeveloperTestInteractor
from culsma_os.console.adapters.settings_mcp import MCPSettingsTools
from tests.support.paths import ROOT


def test_settings_mcp_contains_only_typed_request_delegation():
    tree=ast.parse((ROOT/'src/culsma_os/console/adapters/settings_mcp.py').read_text())
    names={alias.name for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) for alias in node.names}
    assert not any('Repository' in name for name in names)
    assert not names & {'CallerContext','TokenInteractor','DriverProfileInteractor','DeviceProfileInteractor'}
    calls={node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
    assert calls=={'execute','items'}
    for name,method in inspect.getmembers(MCPSettingsTools,inspect.isfunction):
        if name=='settings_tools':continue
        source=inspect.getsource(method)
        assert '.execute(self.raw_credential,' in source
        assert 'self.raw_credential =' not in source
    for owner in (StationConfigurationInteractor,ProgramBindingInteractor,LabwareConfigurationInteractor,ConsoleActivationInteractor,DeveloperTestInteractor,StationSelectionInteractor):
        assert owner.execute is AuthorizedInteractor.execute
        assert owner.required_capability


def test_mcp_configuration_store_can_be_selected_only_at_composition():
    source=(ROOT/'src/culsma_os/console/adapters/settings_mcp.py').read_text()
    assert not any(word in source for word in ['drafts_path','sqlite3','Path(','read_text(','write_text('])
    cli=(ROOT/'src/culsma_os/cli.py').read_text()
    assert "mcp.add_argument('--drafts-db'" in cli and 'drafts_path=args.drafts_db' in cli


def test_every_native_api_surface_has_a_tool_or_an_explicit_authority_boundary():
    import json
    import re
    from culsma_os.console.adapters.mcp import MCPServerAdapter
    from culsma_os.console.adapters.http import ConsoleHTTPHandler
    contract=json.loads((ROOT/'tests/acceptance/manifests/console-tools.json').read_text())
    rows={row['route']:row for row in contract['surfaces']}
    assert len(rows)==len(contract['surfaces'])
    for row in rows.values():
        if 'tools' in row:
            assert row['tools']
            assert all(callable(getattr(MCPServerAdapter,name,None)) for name in row['tools'])
        else:assert row['exception'] in {'operator_only','renderer_only','process_bootstrap'} and row['reason']
    tree=ast.parse(inspect.getsource(ConsoleHTTPHandler))
    endpoints=next(node for node in ast.walk(tree) if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='endpoints' for target in node.targets))
    assert {key.value for key in endpoints.value.keys}<=rows.keys()
    for path in (ROOT/'frontend/console/lib/features').rglob('*.dart'):
        for route in re.findall(r"['\"](/api/v1/[^'\"]+)['\"]",path.read_text()):
            if route.startswith('/api/v1/runs/'):route='/api/v1/runs/{run_id}'
            assert route in rows,(path,route)
    assert not any('confirm' in name for row in rows.values() for name in row.get('tools',[]))


def test_mcp_queries_resident_profiles_and_has_no_vendor_discovery_dependency():
    from culsma_os.console.providers import ConsoleApplicationFactory
    source=inspect.getsource(ConsoleApplicationFactory.build_mcp)
    assert 'RemoteDeviceProfileInteractor(resident)' in source
    assert 'DriverProfileInteractor()' not in source and 'DeviceProfileInteractor(DriverProfileInteractor' not in source
    from culsma_os.device_manager.interactors import RemoteDeviceProfileInteractor,ResidentDeviceProfileInteractor
    for cls in (RemoteDeviceProfileInteractor,ResidentDeviceProfileInteractor):
        imports={node.module or '' for node in ast.walk(ast.parse(inspect.getsource(cls))) if isinstance(node,ast.ImportFrom)}
        assert not any('repository' in name or 'culsma_driver_' in name for name in imports)
    source=inspect.getsource(RemoteDeviceProfileInteractor)
    assert 'configuration-profile' in source and 'fallback' not in source and 'discover(' not in source


def test_station_selection_transport_does_not_restart_or_stop_processes():
    source=inspect.getsource(MCPSettingsTools.select_station_for_next_start)
    assert 'StationSelectionRequest' in source and '.execute(self.raw_credential,' in source
    assert not any(word in source for word in ('subprocess','kill(','Path(','write_text'))
    source=inspect.getsource(StationSelectionInteractor)
    assert not any(word in source for word in ('subprocess','host-stop','shutdown','kill('))
