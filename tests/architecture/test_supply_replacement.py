import ast
from tests.support.paths import ROOT
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.resource_manager.interactors import SupplyInteractionInteractor
from culsma_os.resource_manager.models import SupplyReplacementPort


def test_supply_replacement_keeps_fixed_authorization_and_driver_inversion():
    assert SupplyInteractionInteractor.execute is AuthorizedInteractor.execute
    assert SupplyInteractionInteractor.required_capability=='consumables:simulate'
    for filename in ['interactors.py','models.py','repository.py']:
        source=(ROOT/'src/culsma_os/resource_manager'/filename).read_text()
        assert 'culsma_driver_hamilton' not in source and 'culsma_hamilton' not in source
    for filename in ['http.py','mcp.py']:
        tree=ast.parse((ROOT/'src/culsma_os/console/adapters'/filename).read_text())
        names={a.name for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) for a in n.names}
        assert not names & {'CallerContext','TokenInteractor','SupplyReplacementInteractor','SqliteSupplyLoadRepository'}
        assert not any('Repository' in name for name in names)
    assert {'describe','replace','receipt'}<=set(SupplyReplacementPort.__dict__)
