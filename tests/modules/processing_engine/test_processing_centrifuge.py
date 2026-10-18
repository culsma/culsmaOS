from tests.support.paths import ROOT
from pathlib import Path
import ast
import pytest
from culsma.runtime.state import init_state
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.processing_engine.interactors import AgitationPreparationInteractor, CentrifugePreparationInteractor
from culsma_os.processing_engine.models import CentrifugeIntent
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
from tests.support.processing_engine.processing_centrifuge import CentrifugeMappingFixture


class TestCentrifugeMapping:
    @pytest.mark.parametrize('drive,duration,value,unit,seconds', [
        ('500g','1s',500,'g',1), ('500.5g','0.5min',500.5,'g',30),
        ('1200rpm','0.5s',1200,'rpm',0.5), ('5000g','1h',5000,'g',3600)])
    def test_preserves_generic_request(self,tmp_path,drive,duration,value,unit,seconds):
        pending=CentrifugeMappingFixture().pending(tmp_path,drive,duration)
        intent=AgitationPreparationInteractor().resolve_intent(pending)
        assert type(intent) is CentrifugeIntent
        assert intent.drive_value==value and intent.drive_unit==unit and intent.duration_seconds==seconds
        assert len(intent.targets)==2 and len(set(intent.targets))==2
        assert intent.capability=='centrifuge'
        assert pending.prepared.material_result.delta['op']=='agit'

    def test_scalar_selection_remains_explicit(self,tmp_path):
        intent=CentrifugePreparationInteractor().resolve_intent(CentrifugeMappingFixture().pending(tmp_path,target='w[0]'))
        assert len(intent.targets)==1
        # ProcessingInteractor checks complete physical labware scope after workspace binding.

    def test_environment_is_not_ignored(self,tmp_path):
        with pytest.raises(ValueError,match='PROCESSING_CENTRIFUGE_SCOPE_UNSUPPORTED'):
            CentrifugePreparationInteractor().resolve_intent(CentrifugeMappingFixture().pending(tmp_path,environment=True))

    def test_capability_boundary(self):
        root=ROOT/'src/culsma_os'
        paths=[root/'processing_engine/interactors/centrifuge.py',root/'processing_engine/models.py']
        for path in paths:
            source=path.read_text()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node,ast.ImportFrom):
                    assert not (node.module or '').startswith(('pylabrobot','culsma_pylabrobot','culsma_opentrons'))
                    assert not any('Repository' in n.name for n in node.names)
            assert '3000' not in source and 'MicroSpin' not in source and 'HiG' not in source
        scheduler=(root/'scheduler/interactors.py').read_text()
        assert 'CentrifugeIntent' not in scheduler and 'MicroSpin' not in scheduler

