"""Compose isolated preparation checks from the same execution planners."""
import sqlite3
from types import SimpleNamespace
from culsma_os.device_manager.interactors import DeviceInteractor
from culsma_os.device_manager.repository import SqliteDeviceRepository
from culsma_os.workspace_manager.interactors import SpaceInteractor, LabwareMotionInteractor
from culsma_os.workspace_manager.models import WorkspaceAddress
from culsma_os.workspace_manager.repository import SqliteSpaceRepository, SqliteLabwarePositionRepository
from culsma_os.device_manager.instruments.providers import InstrumentPreparationFactory
from culsma_os.scheduler.conditions import ProcessingConditionProjectionInteractor
from .interactors.transfer_preparation import TransferPreparationInteractor
from .interactors.transfer_intents import CentrifugeTransferInteractor, MagneticTransferInteractor
from .interactors.processing_preparation import ProcessingPreparationInteractor
from .interactors.preflight import ProgramPreflightInteractor


class ProgramPreviewScopeFactory:
    def build(self, snapshot, catalogue, loading, positions):
        connection = sqlite3.connect(':memory:')
        space = SpaceInteractor(SqliteSpaceRepository(connection),
            {k: WorkspaceAddress(**v) for k, v in loading['bindings'].items()},
            {(p['labware'], p['well']): p['capacity_uL'] for p in catalogue['locations']},
            snapshot.labware_geometries)
        space.setup_addresses = set(space.capacities)
        device = DeviceInteractor(SqliteDeviceRepository(connection), None, snapshot)
        motion_repository = SqliteLabwarePositionRepository(connection)
        motion_repository.initialize(snapshot.device_id, snapshot.configuration_revision, positions)
        motion = LabwareMotionInteractor(motion_repository, space, snapshot)
        transfer = TransferPreparationInteractor(space, device, None, snapshot.device_id,
            (CentrifugeTransferInteractor(), MagneticTransferInteractor()),
            preparation=InstrumentPreparationFactory.build_pipetting())
        processing = ProcessingPreparationInteractor(space, device, None, snapshot.device_id,
            devices=InstrumentPreparationFactory.build_processing(motion=motion))
        preflight = ProgramPreflightInteractor(space, snapshot,
            {'Mutation': transfer, 'env_hold': processing, 'agit': processing, 'sep': processing},
            motion=motion, conditions=ProcessingConditionProjectionInteractor(processing, space, snapshot, motion))
        return SimpleNamespace(preflight=preflight, close=connection.close)
