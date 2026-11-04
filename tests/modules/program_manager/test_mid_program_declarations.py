"""Public reference runtime and real SQLite verify local semantic boundaries."""
from copy import deepcopy
from dataclasses import replace
import sqlite3
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.setup_requirements import SetupRequirementsInteractor
from culsma_os.program_manager.interactors.codec import RuntimeCheckpointCodecInteractor
from culsma_os.program_manager.models import EffectResolution, HostContractError
from culsma_os.material_system.interactors import MaterialInteractor
from culsma_os.material_system.repositories.local import LocalMaterialRepository

SOURCE='''let s=tube(capacity=200uL,load=[content(kind=formulation,type=buffer,code="A"):100uL]);
let d=tube(capacity=200uL);d << [s:20uL];
let later=tube(capacity=200uL,load=[content(kind=formulation,type=buffer,code="B"):90uL]);
d << [later:30uL];return d;'''


def compile_source(tmp_path,source=SOURCE):
    p=tmp_path/'protocol.culs';p.write_text(source)
    return CompilationInteractor().compile([p])


def test_loading_projection_preserves_initial_not_projected_amounts(tmp_path):
    c=compile_source(tmp_path);h=HostedRuntimeInteractor();initial=h.create(c.plan,c.state,'run')
    before=h.codec.dumps(c.state)
    rows=SetupRequirementsInteractor(h.codec).inspect(initial)
    assert {r['name']:r['initial_volume_uL'] for r in rows}=={'s':100,'d':0,'later':90}
    assert h.codec.dumps(c.state)==before
    assert h.restore(initial)[0]['confirmed']==[]


def test_replay_keeps_declarations_at_their_execution_point_and_restores(tmp_path):
    c=compile_source(tmp_path);reference=run(c.plan,StubDriver(),deepcopy(c.state))
    h=HostedRuntimeInteractor();checkpoint=h.advance(h.create(c.plan,c.state,'run'))
    first=h.pending(checkpoint)
    assert len(first.before_material_state['containers'])==2
    assert first.declaration_base_fingerprint is None
    ledger_path=tmp_path/'material.sqlite3'
    ledger=LocalMaterialRepository(sqlite3.connect(ledger_path));material=MaterialInteractor(ledger,h.codec)
    for ordinal in range(2):
        ledger.connection.close()
        ledger=LocalMaterialRepository(sqlite3.connect(ledger_path))
        material=MaterialInteractor(ledger,h.codec)
        h=HostedRuntimeInteractor();pending=h.pending(checkpoint)
        material.bind('run',pending,'simulation')
        version=ledger.get('run')[2]
        assert material.bind('run',pending,'simulation')==version
        receipt=ledger.commit_once('run','simulation',pending.effect_id,'receipt'+str(ordinal),
            pending.before_material_state,pending.prepared.material_result.material_state,
            h.codec.fingerprint(pending.prepared.material_result.material_state))
        resolution=EffectResolution(pending.effect_id,receipt.evidence_id,receipt.registration_id,
            receipt.proposed_state_fingerprint,'simulation','OS_MATERIAL_REGISTERED',{})
        checkpoint=h.resume(checkpoint,resolution)
        if ordinal==0:
            second=h.pending(checkpoint)
            assert len(second.before_material_state['containers'])==3
            assert second.declaration_base_fingerprint==receipt.proposed_state_fingerprint
    assert h.result(checkpoint).ok
    assert h.result(checkpoint).state.artifacts['material_state']==reference.state.artifacts['material_state']
    assert ledger.get('run')[1]==reference.state.artifacts['material_state']
    assert ledger.connection.execute('SELECT count(*) FROM os_material_declarations').fetchone()[0]==1
    ledger.connection.close()


def test_invalid_or_unknown_base_cannot_be_adopted(tmp_path):
    c=compile_source(tmp_path);h=HostedRuntimeInteractor();checkpoint=h.advance(h.create(c.plan,c.state,'run'))
    pending=h.pending(checkpoint);repo=LocalMaterialRepository(sqlite3.connect(':memory:'));material=MaterialInteractor(repo,h.codec)
    material.bind('run',pending,'simulation');before=deepcopy(repo.get('run'))
    changed=deepcopy(pending.before_material_state);next(iter(changed['containers'].values()))['volume_uL']=1
    with pytest.raises(ValueError,match='MATERIAL_DECLARATION_BASE_MISMATCH'):
        material.bind('run',replace(pending,before_material_state=changed,declaration_base_fingerprint='wrong'),'simulation')
    repo.mark_uncertain('run','unknown','uncertain-receipt')
    with pytest.raises(ValueError,match='MATERIAL_DECLARATION_BASE_MISMATCH'):
        material.adopt_declared_state('run','simulation','boundary',h.codec.fingerprint(before[1]),changed)
    assert repo.get('run')==before


def test_checkpoint_cannot_forge_local_boundary(tmp_path):
    c=compile_source(tmp_path);h=HostedRuntimeInteractor();checkpoint=h.advance(h.create(c.plan,c.state,'run'))
    data=h.codec.loads(checkpoint);data['pending']=replace(data['pending'],declaration_base_fingerprint='forged')
    with pytest.raises(HostContractError,match='HOST_CHECKPOINT_REPLAY_MISMATCH'):
        HostedRuntimeInteractor().restore(h.codec.dumps(data))


def test_legacy_pending_fingerprint_omits_absent_extension(tmp_path):
    c=compile_source(tmp_path);h=HostedRuntimeInteractor();pending=h.pending(h.advance(h.create(c.plan,c.state,'run')))
    encoded=h.codec.encode(pending)
    assert 'declaration_base_fingerprint' not in encoded['v']
    assert h.codec.dumps(h.codec.decode(encoded))==h.codec.dumps(pending)


def test_unsupported_or_unprojectable_program_is_rejected(tmp_path):
    c=compile_source(tmp_path,SOURCE.replace('return d;', 'img(sample=d,mode="image"); return d;'))
    h=HostedRuntimeInteractor()
    with pytest.raises(ValueError,match='SETUP_PROGRAM_UNSUPPORTED'):
        SetupRequirementsInteractor(h.codec).inspect(h.create(c.plan,c.state,'run'))


def test_projection_keeps_each_statically_bounded_loop_declaration(tmp_path):
    source = SOURCE.replace('return d;', 'repeat i in schedule(start=1,end=2,step=1) { let wash=tube(capacity=200uL,load=[content(kind=formulation,type=buffer,code="W"):10uL]); d << [wash:10uL]; } return d;')
    c=compile_source(tmp_path,source);h=HostedRuntimeInteractor()
    reference=run(c.plan,StubDriver(),deepcopy(c.state))
    assert reference.ok,[d.to_dict() for d in reference.diagnostics]
    rows=SetupRequirementsInteractor(h.codec).inspect(h.create(c.plan,c.state,'loop'))
    assert len(rows)==5
    assert len({r['allocation_id'] for r in rows})==5
    assert sorted(r['initial_volume_uL'] for r in rows)==[0,10,10,90,100]


def test_opentrons_official_simulator_accepts_late_source(tmp_path):
    from culsma_os.bootstrap import OSApplicationFactory
    from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
    c=compile_source(tmp_path)
    context=TransferMatrixFixture().context(tmp_path,c.plan)
    app=OSApplicationFactory().build(context)
    try:
        result=app.execute(c.plan,deepcopy(c.state))
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        reference=run(c.plan,StubDriver(),deepcopy(c.state))
        assert result.state.artifacts['material_state']==reference.state.artifacts['material_state']
        backend=app.host.gateway.port.session.backend
        assert backend.protocol.is_simulating()
        assert len(backend.receipts)==2
    finally:app.close()


def test_declaration_projection_and_material_boundaries_preserve_module_ownership():
    import ast
    root=__import__('pathlib').Path(__file__).resolve().parents[3]/'src/culsma_os'
    for path in ['program_manager/interactors/setup_requirements.py','program_manager/interactors/replay.py']:
        tree=ast.parse((root/path).read_text())
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any('repositories' in name or name.startswith(('culsma_driver_hamilton','opentrons')) for name in imports)
    tree=ast.parse((root/'material_system/repositories/local.py').read_text())
    imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(name.startswith(('culsma.runtime','culsma_os.program_manager.interactors')) for name in imports)

