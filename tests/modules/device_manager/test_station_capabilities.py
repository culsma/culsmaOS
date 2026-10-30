from culsma_os.device_manager.interactors import StationCapabilitiesInteractor


def test_optional_ports_are_explicit_and_never_imply_hardware_detection():
    value=StationCapabilitiesInteractor('opentrons-simulator',layout=True).describe()
    assert value['driver']=='opentrons-simulator' and value['physical_observation'] is False
    assert value['features']['layout']=={'supported':True,'reason':None}
    for key in ['loading_plan','labware_editor','simulated_tip_replacement','fault_test']:
        assert value['features'][key]['supported'] is False and value['features'][key]['reason']
    assert 'manual replenishment' in value['features']['simulated_tip_replacement']['reason']
