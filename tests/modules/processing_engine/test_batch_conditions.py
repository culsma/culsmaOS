from dataclasses import replace
import pytest
from culsma_os.processing_engine.interactors.conditions import BatchProcessingConditionInteractor
from culsma_os.processing_engine.interactors.preparation import ProcessingInteractor
from culsma_os.processing_engine.models import MagneticSeparationIntent,MagneticReleaseIntent
from culsma_os.device_manager.models import DeviceConfigurationSnapshot
from culsma_os.workspace_manager.models import ResolvedContainerRef,SpaceBinding,LayoutSnapshot
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.models import PendingEffect,PreparedRuntimeStep


def values(tmp_path):
    path=tmp_path/'protocol.culs'
    path.write_text('let a=tube(capacity=100uL);let b=tube(capacity=100uL);b << [a:10uL];')
    plan=CompilationInteractor().compile([path]).plan
    step=next(s for p in plan.plans for s in p.steps if s.op=='Mutation')
    pending=PendingEffect('run:sep',PreparedRuntimeStep(step,step,None),{})
    target=ResolvedContainerRef('sample')
    layout=LayoutSnapshot('run','layout',(SpaceBinding(target,'plate','A1',2000,'alloc'),))
    snapshot=DeviceConfigurationSnapshot('device','simulation','revision',(),processing_capabilities={
        'magnetic_separation':{'magnet':{'labware':['plate'],'condition_release':'driver_managed_removal','batch_condition_release':True}}})
    processing=ProcessingInteractor(None,None,None,'device')
    owner=BatchProcessingConditionInteractor(processing,snapshot)
    return owner,pending,MagneticSeparationIntent('sep',(target,),5),layout,snapshot


def test_driver_managed_release_is_a_distinct_covered_system_operation(tmp_path):
    owner,pending,intent,layout,_=values(tmp_path)
    assert owner.before_effect(pending)==()
    description=owner.describe(pending,intent,layout,None)
    assert description['retained_condition']=={'kind':'magnetic_field','release_kind':'driver_managed_removal','targets':['sample']}
    operations=owner.before_effect(pending)
    assert len(operations)==1
    release=operations[0]
    assert release.effect_id=='run:sep/condition-release'
    assert isinstance(release.intent,MagneticReleaseIntent) and release.intent.producer_step_id=='sep'
    assert release.description['system_effect']=='condition_release'
    assert release.description['phases']=={'verify_removed':'returned'}
    assert owner.finish()==()


def test_repeated_retention_and_unadvertised_batch_release_are_rejected(tmp_path):
    owner,pending,intent,layout,snapshot=values(tmp_path)
    owner.describe(pending,intent,layout,None)
    with pytest.raises(ValueError,match='PROCESSING_CONDITION_ALREADY_RETAINED'):
        owner.describe(pending,intent,layout,None)
    snapshot.processing_capabilities['magnetic_separation']['magnet'].pop('batch_condition_release')
    fresh=BatchProcessingConditionInteractor(owner.processing,snapshot)
    with pytest.raises(ValueError,match='BATCH_RETAINED_CONDITION_UNSUPPORTED'):
        fresh.describe(pending,intent,layout,None)
    assert fresh.finish()==()
