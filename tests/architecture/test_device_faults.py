"""Vendor diagnostic interpretation belongs to plugins, not OS guidance."""
import inspect
from culsma_os.driver_framework.interactors import DeviceFaultInteractor, NormalizedReceiptInteractor
from culsma_os.driver_framework.models import DeviceFaultMappingPort
from culsma_os.program_manager.interactors.guidance import RunGuidanceInteractor


def test_core_fault_normalization_and_guidance_have_no_vendor_code_rules():
    for owner in (DeviceFaultInteractor, NormalizedReceiptInteractor, RunGuidanceInteractor):
        source=inspect.getsource(owner)
        assert 'HAM_' not in source and 'DRV_OT_' not in source
        assert 'culsma_driver_hamilton' not in source and 'culsma_opentrons' not in source


def test_mapping_port_and_normalizer_expose_both_execution_and_preparation():
    assert callable(DeviceFaultMappingPort.normalize)
    assert callable(DeviceFaultMappingPort.preparation)
    assert callable(NormalizedReceiptInteractor.preparation)
