from dataclasses import replace
import json
import sqlite3
import pytest
from .support import FakeSessionFactory, ProgramFixture
from culsma_os.device_manager.repository import SqliteDeviceRepository


class TestDeviceBoundary:
    def test_legacy_device_snapshot_preserves_capacity(self):
        connection = sqlite3.connect(":memory:")
        repository = SqliteDeviceRepository(connection)
        value = {
            "device_id": "old",
            "mode": "simulation",
            "configuration_revision": "r1",
            "shared_resources": [],
            "calibration_revision": "simulation",
            "tip_capacity": 24,
        }
        assert repository.decode_snapshot(json.dumps(value)).consumable_capacities == {
            "tips": 24
        }
        connection.close()

    def test_driver_resource_requirements_admit_without_stroke_assumptions(
        self, tmp_path
    ):
        app = FakeSessionFactory().open(tmp_path)
        try:
            app.client.start()
            run_id = app.client.submit_run(ProgramFixture.request())
            operations = app.client.lifecycle.operations
            app.client.lifecycle.runs.advance_ready(run_id)
            from culsma_os.transfer_engine.models import TransferRequest

            prepared = operations.transfer.prepare(
                TransferRequest(run_id, operations.execution.pending(run_id))
            )
            requested = replace(
                prepared, description={"resource_requirements": {"tips": 96}}
            )
            operations.resource.require_consumables(requested)
            too_many = replace(
                requested, description={"resource_requirements": {"tips": 97}}
            )
            with pytest.raises(ValueError, match="OS_CONSUMABLES_INSUFFICIENT"):
                operations.resource.require_consumables(too_many)
            unknown = replace(
                requested, description={"resource_requirements": {"unavailable": 1}}
            )
            with pytest.raises(ValueError):
                operations.resource.require_consumables(unknown)
        finally:
            app.close()

    def test_adapter_converts_to_plugin_owned_request(self):
        pytest.importorskip("culsma_opentrons")
        from culsma_os.driver_framework.adapters.opentrons import (
            OpentronsExecutionAdapter,
        )
        from culsma_os.transfer_engine.models import TransferIntent, TransferAliquot
        from culsma_os.workspace_manager.models import ResolvedContainerRef
        from culsma_opentrons.operations import TransferIntent as DeviceIntent
        from culsma_opentrons.operations import ResolvedContainerRef as DeviceReference

        source = ResolvedContainerRef("invocation::source")
        target = ResolvedContainerRef("invocation::target")
        request = TransferIntent(
            "step",
            target,
            (TransferAliquot(source, 10),),
            requirements=("sterile",),
            environment_requirements=("cold",),
        )
        converted = OpentronsExecutionAdapter(None).convert_intent(request)
        assert (
            type(converted) is DeviceIntent
            and type(converted.target) is DeviceReference
        )
        assert type(converted) is not type(request)
        assert converted.target.container_id == target.container_id
        assert converted.aliquots[0].source.container_id == source.container_id
        assert converted.aliquots[0].volume_uL == 10
        assert converted.requirements == request.requirements
        assert converted.environment_requirements == request.environment_requirements
