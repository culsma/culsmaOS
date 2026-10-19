import ast
from tests.support.paths import ROOT


def test_console_program_architecture():
    base=ROOT/'src/culsma_os'
    path=base/'program_manager/interactors/console_program.py'
    tree=ast.parse(path.read_text())
    owner=next(item for item in tree.body if isinstance(item,ast.ClassDef) and item.name=='ConsoleProgramInteractor')
    assert [item.id for item in owner.bases]==['AuthorizedInteractor']
    assert 'execute' not in {item.name for item in owner.body if isinstance(item,ast.FunctionDef)}
    assert 'required_capability' in {target.id for item in owner.body if isinstance(item,ast.Assign) for target in item.targets if isinstance(target,ast.Name)}
    imports=[item.module or '' for item in ast.walk(tree) if isinstance(item,ast.ImportFrom)]
    assert not any('adapters' in name or 'repositories' in name for name in imports)
    for path in (base/'console/adapters').glob('*.py'):
        tree=ast.parse(path.read_text())
        names={alias.name for item in ast.walk(tree) if isinstance(item,ast.ImportFrom) for alias in item.names}
        assert not names & {'CallerContext','TokenInteractor','FileProgramSourceRepository','CompilationInteractor'}
    repository=(base/'program_manager/repositories/sources.py').read_text()
    assert not any(name in repository for name in ['configuration_drafts','os_attempts','os_material','culsma_opentrons'])
    source=(base/'console/web/programs.js').read_text()
    assert 'sessionStorage' in source and 'request_id' in source
    assert 'innerHTML' not in source and 'setInterval' not in source
