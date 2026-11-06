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


@pytest.mark.parametrize('physical_kind', ['tube', 'well'])
def test_generic_declarations_project_plan_and_bind_without_changing_language_kind(tmp_path, physical_kind):
    import sqlite3
    from culsma_os.workspace_manager.interactors import WorkspacePlanningInteractor, SpaceInteractor
    from culsma_os.workspace_manager.models import WorkspaceAddress
    from culsma_os.workspace_manager.repository import SqliteSpaceRepository
    from culsma_os.program_manager.interactors.setup_requirements import SetupDeclarationProjectionInteractor
    source = tmp_path / 'generic.culs'
    source.write_text('''let buffer = container(capacity=20mL,
        load=[content(kind=formulation, type=buffer, code="BUFFER"):10mL]);
        let waste = container(capacity=20mL); return [buffer, waste];''')
    compiled = CompilationInteractor().compile([source])
    host = HostedRuntimeInteractor()
    checkpoint = host.create(compiled.plan, compiled.state, 'generic')
    demands = SetupRequirementsInteractor(host.codec).inspect(checkpoint)
    assert [d['kind'] for d in demands] == ['container', 'container']
    assert [d['capacity_uL'] for d in demands] == [20000, 20000]
    assert [d['initial_volume_uL'] for d in demands] == [10000, 0]
    locations = [{'labware': 'vessels', 'well': str(i), 'kinds': [physical_kind],
                  'capacity_uL': 25000} for i in (1, 2)]
    layout = WorkspacePlanningInteractor().plan(demands,
        {'schema': 'culsma_workspace_catalogue_v1', 'locations': locations})
    data, _ = host.restore(checkpoint)
    projection = deepcopy(data['initial_state'])
    from culsma.runtime.executor import run
    from culsma_os.driver_framework.adapters.semantic import SemanticReplayDriver
    effects = SetupDeclarationProjectionInteractor(data, projection, host.codec)
    assert run(data['plan'], SemanticReplayDriver(effects), projection).ok
    material = projection.artifacts['material_state']
    before = deepcopy(material)
    space = SpaceInteractor(SqliteSpaceRepository(sqlite3.connect(':memory:')),
        {key: WorkspaceAddress(**value) for key, value in layout['bindings'].items()},
        {('vessels', str(i)): 25000 for i in (1, 2)})
    snapshot = space.bind('generic', material)
    assert len(snapshot.bindings) == 2
    assert space.get('generic') == snapshot
    assert material == before
    assert all(c['metadata'].get('kind') is None for c in material['containers'].values())
    assert all(b.carrier_id is None for b in snapshot.bindings)
