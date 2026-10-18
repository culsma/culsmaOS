"""Generic before-state handoff; no vendor SDK required."""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import pytest
from culsma_os.device_manager.models import DeviceConfigurationSnapshot
from culsma_os.driver_framework.interactors import DriverGatewayInteractor
from culsma_os.driver_framework.models import MaterialExpectation
from culsma_os.transfer_engine.interactors import TransferInteractor
from culsma_os.workspace_manager.models import ResolvedContainerRef, SpaceBinding, LayoutSnapshot


class TestMaterialExpectations:
    def context(self, volume):
        ref=ResolvedContainerRef('resolved-container')
        layout=LayoutSnapshot('run','layout',(SpaceBinding(ref,'plate','A1',360,'allocation'),))
        device=DeviceConfigurationSnapshot('device','simulation','configuration',('gantry',))
        transfer=TransferInteractor(None,None,None,'device')
        return transfer.prepare_context('run',layout,device,
            {'containers':{ref.container_id:{'volume_uL':volume}}}),layout

    def test_capture_preserves_typed_reference(self):
        context,layout=self.context(125)
        assert context.expected_material==(MaterialExpectation(layout.bindings[0].reference,125.0),)
        with pytest.raises(FrozenInstanceError):
            context.expected_material[0].volume_uL=999

    @pytest.mark.parametrize('volume',[None,True,-1,float('nan'),float('inf')])
    def test_unknown_or_invalid_volume_is_not_invented(self,volume):
        with pytest.raises(ValueError,match='TRANSFER_MATERIAL_EXPECTATION_INVALID'):
            self.context(volume)

    def test_optional_port_receives_exact_snapshot(self):
        context,layout=self.context(125)
        received=[]
        port=SimpleNamespace(validate_material=lambda *args:received.append(args))
        gateway=DriverGatewayInteractor(port,None,None)
        gateway.validate_material(context,layout.bindings)
        assert received==[(context.expected_material,layout.bindings)]

    def test_legacy_port_remains_compatible(self):
        context,layout=self.context(125)
        DriverGatewayInteractor(object(),None,None).validate_material(context,layout.bindings)
