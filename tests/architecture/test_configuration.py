import ast
from tests.support.paths import ROOT


def test_configuration_adapter_and_authorization_boundaries():
    for path in (ROOT/'src/culsma_os/console/adapters').glob('*.py'):
        tree=ast.parse(path.read_text())
        imports={alias.name for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) for alias in node.names}
        assert not any('Repository' in name for name in imports)
        assert not imports & {'TokenInteractor','CallerContext','AuthorizedInteractor'}
        assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
            and node.func.id in {'CallerContext','TokenInteractor'} for node in ast.walk(tree))
    path=ROOT/'src/culsma_os/workspace_manager/interactors.py'
    tree=ast.parse(path.read_text())
    concrete=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='StationConfigurationInteractor')
    assert [base.id for base in concrete.bases]==['AuthorizedInteractor']
    assert 'execute' not in {node.name for node in concrete.body if isinstance(node,ast.FunctionDef)}
    assert any(isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='required_capability'
        for target in node.targets) for node in concrete.body)
    for path in (ROOT/'src/culsma_os').rglob('*.py'):
        if 'auth' in path.parts: continue
        tree=ast.parse(path.read_text())
        assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='CallerContext'
            for node in ast.walk(tree)),path
    repo=(ROOT/'src/culsma_os/workspace_manager/repositories/configuration.py').read_text()
    assert not any(name in repo for name in ['os_material','os_runs','os_station','os_devices'])
    assert not any(name in path.read_text() for path in (ROOT/'src/culsma_os/auth').glob('*.py')
                   for name in ['culsma_opentrons','workspace_manager.repositories'])
