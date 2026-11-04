"""Author material descriptions remain language-owned, including during OS replay."""
from copy import deepcopy
import sqlite3
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.setup_requirements import SetupRequirementsInteractor
from culsma_os.program_manager.models import EffectResolution
from culsma_os.material_system.interactors import MaterialInteractor
from culsma_os.material_system.repositories.local import LocalMaterialRepository

SOURCE = '''let source=tube(capacity=60mL,load=[content(kind=formulation,type=buffer,code="OLD"):100uL]);
let plate1=plate(label="Outputs",format="96well",capacity=2000uL);
let a=plate1[A1];a << [source:20uL];
source.materials.replace({source.materials[0]:content(kind=formulation,type=buffer,code="NEW"):80uL});
a << [source:10uL];return a;'''

@pytest.mark.parametrize('trailing',[False,True])
def test_replacement_is_local_and_replay_uses_verified_material_boundary(tmp_path,trailing):
    source=SOURCE.replace('a << [source:10uL];','') if trailing else SOURCE
    path=tmp_path/'replace.culs';path.write_text(source)
    compiled=CompilationInteractor().compile([path]);host=HostedRuntimeInteractor()
    assert not [d for d in [*compiled.semantic.diagnostics,*compiled.typed.diagnostics,*compiled.plan.diagnostics] if d.severity=="error"]
    assert not host.validate_plan(compiled.plan)
    reference=run(compiled.plan,StubDriver(),deepcopy(compiled.state));assert reference.ok
    checkpoint=host.create(compiled.plan,compiled.state,'run')
    rows=SetupRequirementsInteractor(host.codec).inspect(checkpoint)
    assert sorted(r['initial_volume_uL'] for r in rows)==[0,100]
    checkpoint=host.advance(checkpoint)
    repo=LocalMaterialRepository(sqlite3.connect(tmp_path/'ledger.sqlite3'))
    material=MaterialInteractor(repo,host.codec)
    try:
        effects=[]
        while host.pending(checkpoint):
            pending=host.pending(checkpoint)
            assert pending.prepared.runtime_step.op=='Mutation'
            effects.append(pending)
            material.bind('run',pending,'simulation')
            proposed=pending.prepared.material_result.material_state
            receipt=repo.commit_once('run','simulation',pending.effect_id,'device-'+pending.effect_id,
                pending.before_material_state,proposed,host.codec.fingerprint(proposed))
            checkpoint=HostedRuntimeInteractor().resume(checkpoint,EffectResolution(pending.effect_id,
                receipt.evidence_id,receipt.registration_id,receipt.proposed_state_fingerprint,
                'simulation','OS_MATERIAL_REGISTERED',{}))
        result=host.result(checkpoint)
        assert result.ok and result.state.artifacts['material_state']==reference.state.artifacts['material_state']
        assert len(effects)==(1 if trailing else 2)
        last=effects[-1]
        material.adopt_declared_state('run','simulation','final',host.codec.fingerprint(last.prepared.material_result.material_state),result.state.artifacts['material_state'])
        assert material.get('run')[1]==reference.state.artifacts['material_state']
        assert len(repo.connection.execute('SELECT * FROM os_material_declarations').fetchall())==1
        assert len(repo.connection.execute('SELECT * FROM os_material_changes').fetchall())==len(effects)
    finally:repo.connection.close()
