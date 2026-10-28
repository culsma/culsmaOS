import ast
from pathlib import Path
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.console_interaction.interactors import ViewStateReadInteractor, ViewRequestInteractor, RendererSessionInteractor
from tests.support.paths import ROOT


def test_console_interaction_has_only_the_three_layers_and_fixed_entries():
    base=ROOT/'src/culsma_os/console_interaction'
    assert {p.name for p in base.glob('*.py')}=={'__init__.py','interactors.py','models.py','repository.py'}
    for owner in [ViewStateReadInteractor,ViewRequestInteractor,RendererSessionInteractor]:
        assert owner.execute is AuthorizedInteractor.execute
        assert owner.required_capability
    for name in ['interactors.py','repository.py','models.py']:
        tree=ast.parse((base/name).read_text())
        imports={n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        assert not any('console.adapters' in x or 'driver' in x or 'culsma.runtime' in x for x in imports)
        if name=='interactors.py':
            assert not any('repository' in x or 'sqlite' in x for x in imports)
        if name=='repository.py':
            assert not any('auth' in x or 'interactor' in x or 'program_manager' in x for x in imports)
    for p in (ROOT/'src/culsma_os/console/adapters').glob('*.py'):
        tree=ast.parse(p.read_text())
        names={a.name for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) for a in n.names}
        assert not any('Repository' in x for x in names)
        assert not names & {'CallerContext','TokenInteractor'}
    web=(ROOT/'src/culsma_os/console/web/console-shell.js').read_text()
    assert 'innerHTML' not in web and 'eval(' not in web
    assert 'localStorage' not in web and 'sessionStorage' not in web
    assert 'request.expected_revision===this.session.revision' in web
    assert 'openView(' in web and 'revealEntity(' in web
    assert not any(action in web for action in ["action:'start'","action:'confirm'","action:'apply'"])


def test_window_lifecycle_is_frontend_presentation_only():
    web=ROOT/'src/culsma_os/console/web'
    source=(web/'console-windows.js').read_text()
    assert not any(word in source for word in ['fetch(', 'innerHTML', 'eval(', 'localStorage', 'sessionStorage', '/api/'])
    assert not any(action in source for action in ["action:'start'", "action:'cancel'", "action:'apply'", "action:'confirm'"])
    assert 'surface.inert=!enabled' in source
    assert 'this.app.configDirty()' in source
    html=(web/'index.html').read_text()
    assert 'id="window-layer"' in html and 'id="taskbar"' in html
    assert 'class="sidebar"' not in html and 'class="topbar"' not in html
