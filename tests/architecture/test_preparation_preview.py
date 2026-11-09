import ast
from tests.support.paths import ROOT


def test_preparation_scope_has_no_vendor_or_transport_dependencies():
    for relative in ('program_manager/providers.py', 'program_manager/interactors/setup_preflight.py'):
        tree = ast.parse((ROOT/'src/culsma_os'/relative).read_text())
        modules = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any('hamilton' in m or 'opentrons' in m or '.adapters' in m for m in modules)
        calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        assert not set(calls) & {'admit_session', 'check_ready', 'execute_batch', 'execute_transfer', 'prepare_simulation_loading', 'submit', 'start'}


def test_preview_business_interactor_does_not_construct_repositories():
    tree = ast.parse((ROOT/'src/culsma_os/program_manager/interactors/setup_preflight.py').read_text())
    assert not any(isinstance(n, ast.ImportFrom) and 'repositor' in (n.module or '') for n in ast.walk(tree))
