"""Native deck fixtures shared by integration suites."""
import json
from pathlib import Path
from tests.support.integration.shared_setup import SharedSetupHarness


def request(shared, action, fingerprint, **extra):
    return shared.http.request('POST','/api/v1/configuration/labware',shared.headers,
                               {'action':action,'expected_fingerprint':fingerprint,**extra})


def native_station(tmp_path, monkeypatch):
    import culsma_driver_hamilton
    from culsma_driver_hamilton.assembly import build_configuration_profile
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(driver/'reference/LabWare'))
    source=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
    shared=SharedSetupHarness(tmp_path,submit=False)
    configuration=json.loads(shared.context.config_path.read_text())
    configuration['layout']=build_configuration_profile().import_layout(source.read_bytes(),source.name)['configuration']
    configuration['execution']['tips']={'labware':'HTF_B4_TEST','available_positions':['1','2','3','4','5','6']}
    configuration['execution']['capacities_uL']={'WATER_T36_REAR_SITE1':60000,'DWP96_E4':2200}
    configuration['bindings']={};configuration['well_positions']={}
    shared.context.config_path.write_text(json.dumps(configuration))
    return shared


