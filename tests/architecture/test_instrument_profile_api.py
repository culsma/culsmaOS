"""Profile transport and driver dependency boundaries remain explicit."""
import ast
import inspect
from pathlib import Path
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.device_manager.instruments.profile_api import InstrumentProfileInteractor
from culsma_os.console.adapters.instrument_profiles import MCPInstrumentProfileTools
from tests.support.paths import ROOT


def test_profile_operations_use_fixed_authorized_entry():
    assert InstrumentProfileInteractor.execute is AuthorizedInteractor.execute
    assert InstrumentProfileInteractor.required_capability == 'configuration:drafts'
    tree = ast.parse(inspect.getsource(MCPInstrumentProfileTools))
    for method in tree.body[0].body:
        if isinstance(method, ast.FunctionDef):
            calls = [n for n in ast.walk(method) if isinstance(n, ast.Call)]
            assert len(calls) == 2
            assert any(isinstance(n.func, ast.Attribute) and n.func.attr == 'execute' for n in calls)


def test_profile_adapters_never_own_storage_auth_or_vendor_rules():
    text = (ROOT/'src/culsma_os/console/adapters/instrument_profiles.py').read_text()
    assert not any(word in text for word in ('Repository', 'CallerContext', 'TokenInteractor', 'sqlite3', 'culsma_hamilton'))
    text = (ROOT/'src/culsma_os/device_manager/instruments/profile_api.py').read_text()
    assert not any(word in text for word in ('culsma_hamilton', 'culsma_driver_', 'workspace_manager.repositories', 'dispatch(', 'start_run('))


def test_portable_profile_contracts_do_not_import_vendor_or_runtime_adapters():
    for name in ('applicability.py', 'pipetting/profile_parameters.py'):
        text = (ROOT/'src/culsma_os/device_manager/instruments'/name).read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not any(word in (node.module or '') for word in ('culsma_driver_', 'culsma_hamilton', 'console', 'sqlite', 'scheduler'))
        assert 'liquid_class' not in text
    text = (ROOT/'src/culsma_os/console/adapters/instrument_profiles.py').read_text()
    assert 'ProfileOperationContext' not in text
    assert 'translate_step_method' not in text
