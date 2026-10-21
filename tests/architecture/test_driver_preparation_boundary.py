from pathlib import Path
import ast
from tests.support.paths import ROOT


def test_no_parallel_hamilton_program_preparation_inside_os():
    source=ROOT/'src/culsma_os'
    retired={'ProgramBundleInteractor','TransferBundleProjectionInteractor','TransferBundleEffectInteractor',
             'ProgramBundleBindingInteractor','ProgramPreparationPort','ProgramPreparationFactory',
             'ProgramPreparationRequest','ProgramPreparationResult','PreparedProgramArtifact'}
    for path in source.rglob('*.py'):
        classes={n.name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.ClassDef)}
        assert not classes & retired,path
    assert 'culsma.program_bundles' not in (source/'bootstrap.py').read_text()
    assert 'culsma.os_devices' in (source/'bootstrap.py').read_text()
    assert 'build_program_bundle' not in (source/'cli.py').read_text()
    assert 'class SpaceInteractor' in (source/'workspace_manager/interactors.py').read_text()
    assert 'class DeviceExecutionPort' in (source/'driver_framework/models.py').read_text()
