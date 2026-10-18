from pathlib import Path
import sys
import pytest
from culsma_os.bootstrap import OSApplicationFactory


class TestHamiltonCompile:
    def test_existing_hamilton_compiler_is_not_execution(self):
        pytest.importorskip("culsma_driver_hamilton")
        vendor = Path(__file__).resolve().parents[2] / "culsma-driver-hamilton"
        if not vendor.exists():
            pytest.skip("Local vendor reference fixtures unavailable")
        sys.path.insert(0, str(vendor / "tests"))
        try:
            from fixtures.transfer_hsl_case import build_reference_transfer_request

            evidence = (
                OSApplicationFactory()
                .build_hamilton_compiler()
                .compile(build_reference_transfer_request())
            )
            assert (
                evidence.status == "compiled"
                and not evidence.physical_execution_supported
            )
            hsl = evidence.result.artifacts[0].content.decode("ascii")
            assert hsl.count("CulsmaOEM::Channel_Aspirate_002(") == 2
            assert hsl.count("CulsmaOEM::Channel_Dispense_002(") == 2
        finally:
            sys.path.pop(0)
