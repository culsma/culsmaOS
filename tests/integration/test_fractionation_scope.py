"""A fractionation context must not bypass the hosted device contract."""
import pytest
from culsma.runtime.state import init_state
from tests.support.processing_engine.processing_magnetic import MagneticFixture, DECLARATIONS


@pytest.mark.parametrize('program', [
    'density_gradient_program(axis=density,order=top_to_bottom,bins=3)',
    'chromatography_program(axis=retention_time,order=early_to_late,bins=3)',
])
def test_unsupported_fractionation_rejected_before_device_actions(tmp_path, program):
    source = DECLARATIONS + 'sample << [stock];with frac(sample=sample,program=' + program + ') {waste << [sample.contents[0]:20uL];}'
    plan, _, app = MagneticFixture().build(tmp_path, source)
    try:
        result = app.execute(plan, init_state(plan))
        assert not result.ok
        assert any(d.code == 'HOST_OPERATION_UNSUPPORTED' and 'frac' in d.message for d in result.diagnostics)
        assert not app.host.gateway.port.session.backend.protocol.commands()
        assert not app.host.gateway.port.session.magnetic.receipts
    finally:
        app.close()
