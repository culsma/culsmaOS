import ast
import inspect
from pathlib import Path
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.developer_tools.interactors import DeveloperTestInteractor
from culsma_os.console.adapters.http import ConsoleHTTPHandler


def test_developer_module_layers_and_protected_entry():
    import culsma_os.developer_tools as module
    root=Path(module.__file__).parent
    assert {p.name for p in root.glob('*.py')}=={'__init__.py','models.py','interactors.py'}
    assert issubclass(DeveloperTestInteractor,AuthorizedInteractor)
    assert 'execute' not in DeveloperTestInteractor.__dict__
    for path in root.glob('*.py'):
        tree=ast.parse(path.read_text())
        imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        assert not any(n.startswith(('culsma_driver_hamilton','culsma_opentrons')) for n in imports)


def test_http_adapter_only_constructs_the_developer_request():
    source=inspect.getsource(ConsoleHTTPHandler.developer_request)
    for forbidden in ('CallerContext','TokenInteractor','Repository','fault_mapper','resident.execute'):
        assert forbidden not in source
    assert 'FaultTestRequest' in source
