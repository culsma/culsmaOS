import ast
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.workspace_manager.interactors import StationConfigurationInteractor
from tests.support.paths import ROOT


def test_layout_import_preserves_the_existing_authorized_configuration_boundary():
    assert StationConfigurationInteractor.execute is AuthorizedInteractor.execute
    assert StationConfigurationInteractor.required_capability=='configuration:drafts'
    for name in ['workspace_manager/interactors.py','device_manager/interactors.py','console/adapters/http.py']:
        tree=ast.parse((ROOT/'src/culsma_os'/name).read_text())
        imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        assert not any(value.startswith(('culsma_driver_hamilton','culsma_hamilton')) for value in imports)
    adapter=(ROOT/'src/culsma_os/console/adapters/http.py').read_text()
    assert 'self.server.configuration' in adapter and 'profile.import_layout' not in adapter
    presentation=(ROOT/'src/culsma_os/console/web/layout-import.js').read_text()
    assert not any(value in presentation for value in ['DECKLAY','Labware.Cnt','TForm.','HAM_LAYOUT_','innerHTML','apply_configuration'])
    assert 'use.disabled = !report.complete' in presentation
