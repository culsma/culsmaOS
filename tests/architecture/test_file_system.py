import ast
from tests.support.paths import ROOT
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.file_system.interactors import FileReadInteractor


def test_file_system_owns_only_three_layers_and_fixed_authorized_entry():
    base=ROOT/'src/culsma_os/file_system'
    assert {p.name for p in base.glob('*.py')}=={'__init__.py','interactors.py','models.py','repository.py'}
    assert 'source_scope' not in (base/'repository.py').read_text()
    assert FileReadInteractor.execute is AuthorizedInteractor.execute
    assert FileReadInteractor.required_capability=='files:read'
    for path in base.glob('*.py'):
        tree=ast.parse(path.read_text())
        imports={n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        assert not any('driver' in name or 'console.adapters' in name for name in imports)
        if path.name=='repository.py':assert not any('auth' in name or 'interactor' in name for name in imports)
    for path in (ROOT/'src/culsma_os/console/adapters').glob('*.py'):
        names={alias.name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.ImportFrom) for alias in n.names}
        assert not any('Repository' in name for name in names)
        assert not names & {'CallerContext','TokenInteractor'}


def test_workspace_actions_keep_fixed_authorization_and_adapter_delegation():
    from culsma_os.file_system.interactors import FileWorkspaceInteractor
    assert FileWorkspaceInteractor.execute is AuthorizedInteractor.execute
    assert FileWorkspaceInteractor.required_capability=='files:write'
    from culsma_os.console.adapters.mcp import MCPServerAdapter
    for name in ('read_document','create_document','save_document','receive_files'):
        import inspect
        source=inspect.getsource(getattr(MCPServerAdapter,name))
        assert '.execute(self.raw_credential,' in source
        assert 'repository' not in source and 'CallerContext' not in source
