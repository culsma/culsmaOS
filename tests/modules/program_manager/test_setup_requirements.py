"""Loading uses declarations; derived fractions require an explicit physical mapping."""
from copy import deepcopy
import pytest
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.setup_requirements import SetupRequirementsInteractor,SetupRequirementsError

@pytest.mark.parametrize('keep',['pellet','supernatant'])
def test_named_separation_parts_are_not_misreported_as_external_initial_containers(tmp_path,keep):
    source='''let s=tube(capacity=5000uL,load=[content(kind=formulation,type=buffer,code="BUFFER"):100uL]);
let waste=tube(capacity=5000uL);
let parts=sep(sample=s,program=centrifuge_program(drive=300g,keep_source="KEEP"));
waste << [parts[0]];return s;'''.replace('KEEP',keep)
    path=tmp_path/'bound-separation.culs';path.write_text(source)
    compiled=CompilationInteractor().compile([path]);host=HostedRuntimeInteractor()
    checkpoint=host.create(compiled.plan,compiled.state,'inspect')
    before=host.codec.dumps(deepcopy(compiled.state))
    with pytest.raises(SetupRequirementsError,match='SETUP_SEPARATION_OUTPUT_MAPPING_REQUIRED') as rejected:
        SetupRequirementsInteractor(host.codec).inspect(checkpoint)
    diagnostic=rejected.value.diagnostics[0]
    assert diagnostic['basis']=='language_projection' and not diagnostic['physical_observation']
    assert len(diagnostic['items'])==1
    item=diagnostic['items'][0]
    assert item['program_kind']=='centrifuge_program'
    assert item['source_container_id']!=item['container_id']
    assert item['producer_step_id'] and item['part'] in {'0','1'}
    assert host.codec.dumps(compiled.state)==before
    assert host.restore(checkpoint)[0]['confirmed']==[]
