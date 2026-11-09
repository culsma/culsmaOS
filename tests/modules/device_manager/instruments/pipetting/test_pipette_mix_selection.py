from types import SimpleNamespace

import pytest

from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.transfer_preparation import TransferPreparationInteractor


@pytest.mark.parametrize('supported', [False, True])
@pytest.mark.parametrize('volume', [0, 100])
def test_driver_opt_in_executes_quantified_self_mix_without_changing_material(tmp_path, supported, volume):
    source = tmp_path/'mix.culs'
    source.write_text('let s=tube(capacity=2mL,load=['
        f'content(kind=formulation,type=buffer,code="B"):200uL]); s << [s:{volume}uL];')
    compiled = CompilationInteractor().compile([source])
    host = HostedRuntimeInteractor()
    pending = host.pending(host.advance(host.create(compiled.plan, compiled.state, 'mix')))
    device = SimpleNamespace(transfer_selection_capabilities=('pipette_mix',) if supported else ())
    preparation = SimpleNamespace(require_supported=lambda requirements, device: None)
    interactor = TransferPreparationInteractor(None, SimpleNamespace(get=lambda _: device),
        None, 'test', preparation=preparation)
    decision = interactor.resolve_execution(pending)
    if supported and volume:
        assert decision.intent.selection_kind == 'pipette_mix'
        assert decision.intent.aliquots[0].source == decision.intent.target
        assert decision.intent.aliquots[0].volume_uL == 100
    else:
        assert decision.intent is None
    proposal = pending.prepared.material_result
    assert proposal.material_state == pending.before_material_state
