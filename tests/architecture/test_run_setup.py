from pathlib import Path
import ast
from tests.support.paths import ROOT


def test_setup_planning_and_persistence_stay_in_existing_owning_modules():
    paths = {
        'program_manager/interactors/setup.py': 'RunSetupInteractor',
        'program_manager/interactors/setup_requirements.py': 'SetupRequirementsInteractor',
        'program_manager/interactors/setup_command.py': 'RunSetupCommandInteractor',
        'program_manager/repositories/setup.py': 'SqliteRunSetupRepository',
        'workspace_manager/interactors.py': 'WorkspacePlanningInteractor',
    }
    source = ROOT/'src/culsma_os'
    for name, cls in paths.items():
        tree=ast.parse((source/name).read_text())
        assert any(isinstance(n,ast.ClassDef) and n.name==cls for n in ast.walk(tree))
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any(i.startswith(('culsma_driver_hamilton','culsma_opentrons','subprocess','socket')) for i in imports)
        if '/interactors/' in name:
            assert not any(a.name.startswith(('Sqlite','Local')) and a.name.endswith('Repository')
                for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) for a in n.names)
    cli=ast.parse((source/'cli.py').read_text())
    assert not any('Repository' in a.name for n in ast.walk(cli) if isinstance(n,ast.ImportFrom) for a in n.names)


def test_runtime_and_all_device_dispatch_paths_share_the_setup_gate():
    source=ROOT/'src/culsma_os'
    gateway=ast.parse((source/'driver_framework/interactors.py').read_text())
    cls=next(n for n in gateway.body if isinstance(n,ast.ClassDef) and n.name=='DriverGatewayInteractor')
    for name in ['execute','execute_group_member','execute_collective_group','execute_group_wave']:
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='dispatch_guard'
                   for n in ast.walk(method)), name
    guard=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='dispatch_guard')
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='require_dispatch' for n in ast.walk(guard))
    assert 'require_dispatch(run_id)' in (source/'program_manager/interactors/execution.py').read_text()


def test_shared_setup_uses_fixed_authorization_and_thin_transport_adapters():
    from culsma_os.auth.interactors import AuthorizedInteractor
    from culsma_os.program_manager.interactors.setup_interaction import (
        SetupInteractionInteractor, SetupConfirmationInteractor, AutomationObservationInteractor)
    for cls in [SetupInteractionInteractor,SetupConfirmationInteractor,AutomationObservationInteractor]:
        assert cls.execute is AuthorizedInteractor.execute
        assert cls.required_capability
    source=ROOT/'src/culsma_os'
    for name in ['console/adapters/http.py','console/adapters/mcp.py']:
        tree=ast.parse((source/name).read_text())
        imports={a.name for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) for a in n.names}
        assert not imports & {'CallerContext','TokenInteractor','SessionCredentialRepository'}
        assert not any('Repository' in name for name in imports)
    mcp=ast.parse((source/'console/adapters/mcp.py').read_text())
    methods={n.name for n in ast.walk(mcp) if isinstance(n,ast.FunctionDef)}
    assert {'loading_plan','revise_loading_plan','begin_loading','loading_request_status'} <= methods
    assert not any('confirm' in name for name in methods)
    web=(source/'console/web/setup.js').read_text()
    assert 'setInterval' not in web and 'setupFingerprint' in web
    assert "action:'setup.confirm'" in web and "field:'/setup/loaded'" in web
