"""Real external driver conversion through HTTP and accessible file-upload controls."""
import json
import os
from pathlib import Path
import subprocess
import pytest
from tests.support.paths import ROOT
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.skipif(not all(os.environ.get(key) for key in ['CULSMA_OS_BROWSER_MODULES','CULSMA_OS_CHROME']),
    reason='Explicit browser environment required')
def test_native_import_reviews_real_layout_and_only_accepts_lossless_conversion(tmp_path,monkeypatch):
    culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
    from culsma_driver_hamilton.assembly import build_layout_exporter
    driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    root=driver/'reference/LabWare';monkeypatch.setenv('CULSMA_HAMILTON_LABWARE_ROOT',str(root))
    config=json.loads((driver/'examples/os-transfer-input/setup.json').read_text())['layout']
    exported=build_layout_exporter(root).execute(config)
    generated=tmp_path/'generated.lay'
    generated.write_bytes(next(a.content for a in exported.artifacts if a.name=='layout_generated.lay'))
    original=driver/'examples/test32-water-plate-heat/revision2/test32_water_plate_heat_deck_r2.lay'
    codec=build_layout_exporter(root).archive
    raw=generated.read_bytes();section,end=codec.read_section(raw,8)
    from dataclasses import replace
    fields=dict(section.fields);fields['Labware.1.File']='unknown/missing.rck'
    unsupported=tmp_path/'unsupported.lay'
    unsupported.write_bytes(codec.wrap(raw[:8]+codec.write_section(replace(section,fields=tuple(sorted(fields.items()))))+raw[end:raw.rfind(b'\r\n* $$author=')]))
    output=ROOT/'run-artifacts/ui-tests/layout-import.png';output.parent.mkdir(parents=True,exist_ok=True)
    with SharedSetupHarness(tmp_path) as shared:
        result=subprocess.run([os.environ.get('CULSMA_OS_NODE','node'),str(ROOT/'tests/support/console/layout_import_browser.mjs'),
            shared.url,str(original),str(generated),str(output),str(ROOT/'tests/modules/console/goldens'),str(unsupported)],capture_output=True,text=True,cwd=ROOT,timeout=60)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['roundtrip_configuration']==config
        assert shared.status(shared.run_id)['status']=='awaiting_setup'
        assert not shared.backend.calls
