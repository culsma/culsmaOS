"""Saved OS layout -> installed optional driver -> native VENUS archive, no device I/O."""
import base64
from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile
import pytest
from culsma_os.device_manager.interactors import DeviceProfileInteractor
from culsma_os.workspace_manager.models import StationConfigurationRequest
from tests.support.workspace_manager.configuration import ConfigurationFixture


@pytest.mark.parametrize('carrier,model,track,site,origin', [
    ('CAR_5DWP', 'Ham_DW_Rgt_96_L', '16', '5', (387, 146, 178.5)),
    ('RGT_CAR_5R60_A00', 'RGT_CONT_60ML_BC_A00', '1', '1', (43.75, 464.15, 163.2)),
    ('RGT_CAR_4R200_A00', 'RGT_200ml_A00', '1', '1', (55, 528.55, 134.1)),
    ('TIP_CAR_288_HTF_C00', 'HTF_P', '1', '1', (46, 502, 214.7)),
    ('TIP_CAR_288_HTF_B00', 'HTF_P', '1', '1', (59.4, 501.95, 215.15)),
    ('PLT_CAR_L5FLEX_MD_A00', 'Ham_DW_Rgt_96_L', '1', '1', (60.75, 530, 215.8)),
])
def test_saved_layout_reaches_native_export_without_existing_lay(tmp_path, carrier, model, track, site, origin):
    vendor = pytest.importorskip('culsma_driver_hamilton')
    from culsma_driver_hamilton.assembly import build_layout_exporter
    from culsma_driver_hamilton.interactors.configuration_profile_interactor import HamiltonConfigurationProfileInteractor
    root = Path(vendor.__file__).resolve().parents[2]/'reference/LabWare'
    if not root.exists(): pytest.skip('Private local vendor geometry fixtures unavailable')
    profile = HamiltonConfigurationProfileInteractor(build_layout_exporter(root))
    class Discovery:
        def discover(self): return {'hamilton-layout':profile}, ()
    fixture=ConfigurationFixture(tmp_path/'drafts.sqlite3')
    fixture.interactor.profiles=DeviceProfileInteractor(Discovery())
    configuration={'schema':'hamilton_layout_proposal_v1','deck_model':'STAR-54',
        'carriers':{'plates':{'model':carrier,'track':track}},
        'labware':{'source':{'model':model,'carrier':'plates','site':site}}}
    draft=fixture.execute(StationConfigurationRequest('create',title='Hamilton',driver='hamilton-layout',configuration=configuration))['draft']
    exported=fixture.execute(StationConfigurationRequest('export_layout',draft['draft_id'],1))
    artifact=exported['layout_artifact']; raw=base64.b64decode(artifact['content'],validate=True)
    assert sha256(raw).hexdigest()==artifact['sha256']
    assert artifact['configuration_sha256']==draft['fingerprint']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert json.loads(archive.read('configuration.json'))==configuration
        manifest=json.loads(archive.read('layout-manifest.json'))
        plate=next(p for p in manifest['placements'] if p['name']=='source')
        assert (plate['x_mm'],plate['y_mm'],plate['z_mm'])==pytest.approx(origin)
        execution = manifest['execution_layout']
        assert execution['layout']['sha256'] == sha256(archive.read('layout_generated.lay')).hexdigest()
        assert execution['layout_objects'][0]['labware_id'] == 'source'
    assert exported['activation']=='not_applied'
    assert not artifact['physical_execution_supported']
    # Generic configuration JSON export keeps its original behavior.
    plain=fixture.execute(StationConfigurationRequest('export',draft['draft_id'],1))
    assert 'layout_artifact' not in plain and plain['configuration']==configuration


def test_flutter_layout_fixture_matches_current_driver_metadata():
    pytest.importorskip('culsma_driver_hamilton')
    from culsma_driver_hamilton.interactors.configuration_profile_interactor import HamiltonConfigurationProfileInteractor
    profile = HamiltonConfigurationProfileInteractor().describe()
    root = Path(__file__).resolve().parents[2]
    fixture = json.loads((root/'frontend/console/test/fixtures/hamilton_profile.json').read_text())
    assert fixture['layout'] == profile['layout']
    assert fixture['fields'] == profile['fields']
