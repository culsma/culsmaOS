"""Real program and official Opentrons simulator regression for the magnetic device entry."""
from dataclasses import replace
import pytest
from culsma.runtime.executor import init_state
from culsma_os.program_manager.models import RunRequest
from culsma_os.device_manager.instruments.magnet.interactors import MagnetExecutionPreparationInteractor
from culsma_os.device_manager.instruments.magnet.models import MagneticSeparationIntent
from tests.support.processing_engine.processing_magnetic import MagneticFixture


def test_program_routes_magnetic_preparation_to_device_manager(tmp_path):
    fixture = MagneticFixture()
    plan, context, app = fixture.build(tmp_path)
    try:
        processing = app.client.lifecycle.operations.planners['sep']
        assert isinstance(processing.devices.preparers['magnetic_separation'], MagnetExecutionPreparationInteractor)
        identity, pending = fixture.waiting_separation(app, plan)
        intent = processing.resolve_intent(pending)
        assert isinstance(intent, MagneticSeparationIntent)
        app.client.lifecycle.operations.dispatch_ready(identity)
        app.client.run_until_settled(identity)
        result = app.client.result(identity)
        fixture.compare(app, plan, result)
    finally:
        app.close()


def test_device_entry_rejects_partial_plate_and_missing_module(tmp_path):
    fixture = MagneticFixture()
    plan, context, app = fixture.build(tmp_path)
    try:
        identity, pending = fixture.waiting_separation(app, plan)
        processing = app.client.lifecycle.operations.planners['sep']
        owner = processing.devices.preparers['magnetic_separation']
        intent = processing.resolve_intent(pending)
        layout = processing.space.preview(identity, pending.before_material_state, app.client.execution.allocations(identity))
        snapshot = processing.device.get(processing.device_id)
        other = replace(layout.bindings[0], reference=type(intent.targets[0])('unselected'),
                        labware=next(b.labware for b in layout.bindings if b.reference in intent.targets), well='A2')
        with pytest.raises(ValueError, match='PROCESSING_COLLATERAL_EXPOSURE'):
            owner.bind_intent(intent, replace(layout,bindings=(*layout.bindings,other)),snapshot)
        with pytest.raises(ValueError, match='PROCESSING_MODULE_UNAVAILABLE'):
            owner.bind_intent(intent,layout,replace(snapshot,processing_capabilities={}))
    finally:
        app.close()
