"""Mode labels never assume a simulator or physical execution without a record."""
import pytest
from culsma_os.program_manager.interactors.host import RunReportInteractor


@pytest.mark.parametrize('mode,expected', [('simulation','simulation'),('physical','physical'),
    (None,'unknown'),('device','unknown'),('','unknown')])
def test_execution_mode_is_explicit(mode, expected):
    assert RunReportInteractor.execution_mode(None,mode)==expected
