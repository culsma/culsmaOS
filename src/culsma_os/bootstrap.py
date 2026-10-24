"""Composition only: select factories and inject all concrete implementations."""

from importlib.metadata import entry_points
from .program_manager.interactors.semantics import HostedRuntimeInteractor
from .program_manager.interactors.codec import RuntimeCheckpointCodecInteractor
from .driver_framework.models import DriverLoadError
from .storage import DatabaseConnection
from .api import CulsmaOSClient, OSApplication
from .program_manager.repositories.runs import SqliteTaskRepository
from .program_manager.interactors.preparation import PreparationInteractor
from .program_manager.interactors.projection import GroupProjectionInteractor
from .program_manager.interactors.runs import TaskInteractor
from .program_manager.interactors.execution import ExecutionHostInteractor
from .program_manager.interactors.run_state import RunStateInteractor
from .program_manager.interactors.host import OSRunHostInteractor, RunReportInteractor
from .device_manager.repository import SqliteDeviceRepository
from .device_manager.interactors import DeviceInteractor
from .device_manager.models import DeviceConfigurationSnapshot, ExecutionFeedbackCapabilities
from .workspace_manager.repository import SqliteSpaceRepository
from .workspace_manager.interactors import SpaceInteractor
from .driver_framework.interactors import (
    DriverGatewayInteractor,
    NormalizedReceiptInteractor,
    DriverLoaderInteractor,
)
from .transfer_engine.interactors import TransferInteractor, MagneticTransferInteractor, CentrifugeTransferInteractor
from .processing_engine.interactors import (ProcessingInteractor, ThermalHoldPreparationInteractor, AgitationPreparationInteractor, SeparationPreparationInteractor, CentrifugeMethodBindingInteractor)
from .resource_manager.repository import SqliteResourceRepository, SqliteRunReservationRepository
from .resource_manager.interactors import ResourceInteractor, ConsumableInteractor, RunReservationInteractor, StationUsageInteractor
from .program_manager.interactors.safety import RunSafetyInteractor
from .event_journal.repositories.evidence import SqliteEvidenceRepository
from .event_journal.repositories.events import SqliteRunEventRepository
from .event_journal.interactors.evidence import EvidenceInteractor
from .material_system.repositories.local import LocalMaterialRepository
from .material_system.interactors import MaterialInteractor
from .scheduler.repository import SqliteOperationRepository
from .scheduler.interactors import RunSchedulerInteractor, OperationSchedulerInteractor, GroupOperationInteractor, ExecutionStrategyInteractor
from .recovery_manager.interactors import RecoveryInteractor
from .lifecycle_manager.interactors import LifecycleInteractor, RunFinalizationInteractor, HostOwnershipInteractor


class OpentronsSessionFactory:
    """Compose OS DTOs from the plugin's public session description."""

    def build(self, context):
        from culsma_opentrons.plugin import SimulatorSessionFactory
        from .driver_framework.adapters.opentrons import OpentronsExecutionAdapter

        session = SimulatorSessionFactory().create_from_file(
            context.config_path, context.artifacts_dir, state_dir=getattr(context, "device_state_dir", None)
        )
        try:
            description = session.describe_session()
            snapshot = DeviceConfigurationSnapshot(
                description.device_id,
                description.mode,
                description.configuration_revision,
                description.shared_resources,
                supports_transfer=True,
                transfer_requirements=getattr(description, "transfer_requirements", ()),
                motion_capabilities=getattr(description, "motion_capabilities", {}),
                consumable_capacities=description.consumable_capacities,
                labware_geometries=description.labware_geometries,
                transfer_channels=description.transfer_channels,
                processing_capabilities=description.processing_capabilities,
                feedback_capabilities=(ExecutionFeedbackCapabilities(description.feedback_completion_units)
                    if getattr(description, "feedback_completion_units", None) is not None else None),
            )
            return (
                OpentronsExecutionAdapter(session),
                snapshot,
                description.positions,
                description.capacities,
                NormalizedReceiptInteractor(),
            )
        except BaseException:
            session.close()
            raise


class OSApplicationFactory:

    def __init__(self, session_factories=None, execution_strategy_factory=None):
        self.execution_strategy_factory = (ExecutionStrategyInteractor.configured if execution_strategy_factory is None
                                           else execution_strategy_factory)
        self.session_factories = (
            {"opentrons-simulator": OpentronsSessionFactory()}
            if session_factories is None
            else session_factories
        )

    def build(self, context):
        from dataclasses import replace
        from .resource_manager.interactors import StationPathInteractor
        station_path = StationPathInteractor().database_path(context)
        context = replace(context, device_state_dir=StationPathInteractor().device_state_directory(context))
        factory = self.session_factories.get(context.driver_name)
        if factory is None:
            matches = list(
                entry_points(group="culsma.os_devices", name=context.driver_name)
            )
            if len(matches) != 1:
                raise DriverLoadError(f"OS_DEVICE_NOT_SUPPORTED: {context.driver_name}")
            factory = matches[0].load()()
        port, snapshot, positions, capacities, receipt_mapper = factory.build(context)
        database = DatabaseConnection(context.database_path)
        connections = [database.open() for _ in range(8)]
        connections.extend(DatabaseConnection(station_path).open() for _ in range(2))
        codec = RuntimeCheckpointCodecInteractor()
        task_repository = SqliteTaskRepository(connections[0])
        device = DeviceInteractor(SqliteDeviceRepository(connections[8], connections[1]), port, snapshot)
        from .program_manager.interactors.workspace import RunWorkspaceInteractor, WorkspaceCheckpointInteractor
        space = SpaceInteractor(
            SqliteSpaceRepository(connections[2]), positions, capacities, snapshot.labware_geometries,
            RunWorkspaceInteractor(task_repository, codec, strict=context.workspace_config_path is not None),
        )
        gateway = DriverGatewayInteractor(port, device, receipt_mapper)
        transfer = TransferInteractor(space, device, gateway, snapshot.device_id, (CentrifugeTransferInteractor(), MagneticTransferInteractor()))
        from .workspace_manager.repository import SqliteLabwarePositionRepository
        from .workspace_manager.interactors import LabwareMotionInteractor
        motion = LabwareMotionInteractor(SqliteLabwarePositionRepository(connections[9], connections[2],
            str(context.database_path.resolve())), space, snapshot, str(context.database_path.resolve()))
        processing = ProcessingInteractor(space, device, gateway, snapshot.device_id,
            {"env_hold": ThermalHoldPreparationInteractor(), "agit": AgitationPreparationInteractor(), "sep": SeparationPreparationInteractor()},
            {"centrifuge": CentrifugeMethodBindingInteractor()}, placement=motion)
        from .program_manager.interactors.preflight import ProgramPreflightInteractor
        from .processing_engine.interactors.conditions import ProcessingConditionProjectionInteractor
        condition_projection = ProcessingConditionProjectionInteractor(processing, space, snapshot, motion)
        preflight = ProgramPreflightInteractor(space, snapshot,
            {"Mutation": transfer, "env_hold": processing, "agit": processing, "sep": processing},
            motion=motion, conditions=condition_projection)
        host = HostedRuntimeInteractor(processing_capabilities=snapshot.processing_capabilities, preflight=preflight)
        preparation = PreparationInteractor(host, self.build_workspace_catalog(context), WorkspaceCheckpointInteractor(codec))
        import os
        from .resource_manager.interactors import StationPathInteractor
        station_id = context.station_id or os.environ.get("CULSMA_OS_STATION_ID", "local")
        station_path = StationPathInteractor().database_path(context)
        station_repository = SqliteRunReservationRepository(DatabaseConnection(station_path).open(), station_path.with_suffix(".dispatch.lock"))
        usage = StationUsageInteractor(station_repository)
        evidence = EvidenceInteractor(
            SqliteEvidenceRepository(connections[4]),
            SqliteRunEventRepository(connections[7]),
            usage,
        )
        resource = ResourceInteractor(
            SqliteResourceRepository(connections[3]),
            ConsumableInteractor(device, evidence),
        )
        state = RunStateInteractor(task_repository, host, evidence)
        tasks = TaskInteractor(task_repository, preparation, state)
        execution = ExecutionHostInteractor(tasks, host, state)
        material = MaterialInteractor(LocalMaterialRepository(connections[5]), codec)
        operation_repository = SqliteOperationRepository(connections[6])
        from .processing_engine.interactors.conditions import ProcessingConditionInteractor
        from .scheduler.interactors import MotionSchedulerInteractor
        motions = MotionSchedulerInteractor(motion, execution, gateway, resource, evidence, device, state)
        conditions = ProcessingConditionInteractor(evidence, gateway, resource, motions)
        safety = RunSafetyInteractor(tasks, execution, evidence, material, conditions, motions)
        reservations = RunReservationInteractor(station_repository, safety, station_id,
            str(context.database_path.resolve()), snapshot, usage)
        resource.reservations = reservations
        gateway.reservations = reservations
        projection = GroupProjectionInteractor(codec)
        from .scheduler.interactors import LogicalEffectInteractor
        logical = LogicalEffectInteractor(transfer, evidence, material, codec)
        groups = GroupOperationInteractor(operation_repository, execution, transfer, resource, device, space, gateway, evidence, material, state, projection, logical)
        operations = OperationSchedulerInteractor(
            operation_repository,
            execution,
            transfer,
            resource,
            device,
            space,
            gateway,
            evidence,
            material,
            state,
            groups,
            logical,
            planners={"Mutation": transfer, "env_hold": processing, "agit": processing, "sep": processing},
            motions=motions,
            conditions=conditions,
        )
        from .program_manager.repositories.setup import SqliteRunSetupRepository
        from .program_manager.interactors.setup import RunSetupInteractor
        from .program_manager.interactors.setup_requirements import SetupRequirementsInteractor
        from .workspace_manager.interactors import WorkspacePlanningInteractor
        catalogue = port.describe_workspace() if snapshot.setup_required else None
        space.setup_addresses = ({(p['labware'], p['well']) for p in catalogue['locations']}
                                 if catalogue is not None else {(a.labware, a.well) for a in positions.values()})
        setup = RunSetupInteractor(SqliteRunSetupRepository(connections[0]), tasks, state, host, codec,
            SetupRequirementsInteractor(codec), WorkspacePlanningInteractor(), catalogue, snapshot, reservations, evidence, space.workspaces, device)
        tasks.setup = setup
        gateway.setup = setup
        runs = RunSchedulerInteractor(tasks, execution, reservations, device, evidence)
        finalization = RunFinalizationInteractor(tasks, state, safety, reservations, conditions, resource, evidence)
        strategy = self.execution_strategy_factory(tasks, runs, operations)
        recovery = RecoveryInteractor(
            tasks, execution, evidence, material, state, resource, projection, logical, finalization, motions, strategy
        )
        lifecycle = LifecycleInteractor(
            tasks,
            runs,
            operations,
            recovery,
            state,
            device,
            evidence,
            snapshot.device_id,
            conditions,
            finalization,
            execution_strategy=strategy,
        )
        report = RunReportInteractor(tasks, execution, material, setup)
        client = CulsmaOSClient(tasks, lifecycle, execution, report)
        return OSApplication(
            OSRunHostInteractor(
                tasks, lifecycle, execution, material, connections, gateway,
                report
            ),
            client,
        )

    def build_resident_host(self, settings):
        from .lifecycle_manager.interactors import ResidentHostInteractor, ResidentStatusInteractor, ResidentConfigurationInteractor
        from .lifecycle_manager.repository import SqliteResidentConfigurationRepository
        from .program_manager.repositories.queue import SqliteRunQueueRepository
        from .program_manager.interactors.compilation import CompilationInteractor
        from .program_manager.interactors.resident import ResidentCommandInteractor
        from .program_manager.adapters.resident import ResidentSocketAdapter
        from dataclasses import replace
        connection = DatabaseConnection(settings.context.database_path).open()
        configuration = ResidentConfigurationInteractor(SqliteResidentConfigurationRepository(connection),connection)
        settings = replace(settings,context=configuration.restore(settings.context))
        status = ResidentStatusInteractor(settings.poll_interval)
        command_factory = ResidentCommandFactory(self)
        commands = command_factory.build(settings.context,status,configuration)
        return ResidentHostInteractor(settings,status,HostLeaseFactory().build(settings.context,settings.socket_path),
            commands,ResidentSocketAdapter(settings.socket_path,commands),ResidentWorkerFactory(self),configuration,command_factory)

    def build_hamilton_compiler(self):
        from culsma_driver_hamilton.assembly import build_transfer_compiler
        from .driver_framework.adapters.hamilton import HamiltonCompilationAdapter
        from .driver_framework.interactors import HamiltonCompilationInteractor

        return HamiltonCompilationInteractor(
            HamiltonCompilationAdapter(build_transfer_compiler())
        )

    def build_device_inspector(self, context):
        from .storage import ReadOnlyDatabaseSnapshot
        from .device_manager.repository import SqliteDeviceInspectionRepository
        from .device_manager.interactors import DeviceInspectionInteractor
        from .workspace_manager.repository import SqliteWorkspaceInspectionRepository
        from .workspace_manager.interactors import WorkspaceInspectionInteractor
        from .resource_manager.repository import SqliteResourceInspectionRepository
        from .resource_manager.interactors import ResourceInspectionInteractor, StationPathInteractor
        from .event_journal.repositories.inspection import SqliteEvidenceInspectionRepository
        from .event_journal.interactors.inspection import EvidenceInspectionInteractor
        local = ReadOnlyDatabaseSnapshot(context.database_path)
        station_path = StationPathInteractor().database_path(context)
        station = ReadOnlyDatabaseSnapshot(station_path)
        return DeviceInspectionInteractor(SqliteDeviceInspectionRepository(station, local), local,
            WorkspaceInspectionInteractor(SqliteWorkspaceInspectionRepository(station, local)),
            ResourceInspectionInteractor(SqliteResourceInspectionRepository(local, station), station),
            EvidenceInspectionInteractor(SqliteEvidenceInspectionRepository(local)), station_path, station)

    def build_run_inspector(self, context):
        from .program_manager.interactors.control import RunInspectionInteractor
        from .program_manager.interactors.host import RunReportInteractor
        connections = [DatabaseConnection(context.database_path).open() for _ in range(2)]
        host = HostedRuntimeInteractor()
        repository = SqliteTaskRepository(connections[0])
        state = RunStateInteractor(repository, host, None)
        from .program_manager.interactors.workspace import WorkspaceCheckpointInteractor
        tasks = TaskInteractor(repository, PreparationInteractor(host, self.build_workspace_catalog(context),
            WorkspaceCheckpointInteractor(RuntimeCheckpointCodecInteractor())), state)
        execution = ExecutionHostInteractor(tasks, host, state)
        material = MaterialInteractor(LocalMaterialRepository(connections[1]), RuntimeCheckpointCodecInteractor())
        from .program_manager.repositories.setup import SqliteRunSetupRepository
        from .program_manager.interactors.setup import RunSetupInspectionInteractor
        report = RunReportInteractor(tasks, execution, material,
            RunSetupInspectionInteractor(SqliteRunSetupRepository(connections[0])))
        from .storage import ReadOnlyDatabaseSnapshot
        from .program_manager.interactors.run_evidence import RunEvidenceInteractor
        from .event_journal.interactors.inspection import EvidenceInspectionInteractor
        from .event_journal.repositories.inspection import SqliteEvidenceInspectionRepository
        from .material_system.interactors import MaterialInspectionInteractor
        from .material_system.repositories.inspection import SqliteMaterialInspectionRepository
        snapshot = ReadOnlyDatabaseSnapshot(context.database_path)
        evidence = RunEvidenceInteractor(snapshot,
            EvidenceInspectionInteractor(SqliteEvidenceInspectionRepository(snapshot)),
            MaterialInspectionInteractor(SqliteMaterialInspectionRepository(snapshot)))
        return RunInspectionInteractor(tasks, report, connections, evidence)

    def build_workspace_catalog(self, context):
        if context.workspace_config_path is None:
            return None
        from .program_manager.interactors.workspace import ProgramWorkspaceCatalogInteractor
        from .program_manager.repositories.workspace import FileWorkspaceCatalogRepository
        from .program_manager.interactors.compilation import CompilationInteractor
        from .workspace_manager.interactors import WorkspaceProfileInteractor
        return ProgramWorkspaceCatalogInteractor(FileWorkspaceCatalogRepository(context.workspace_config_path),
            CompilationInteractor(), WorkspaceProfileInteractor(), RuntimeCheckpointCodecInteractor())

    def build_run_controller(self):
        from .program_manager.interactors.control import RunControlInteractor
        return RunControlInteractor(self, HostOwnershipInteractor(HostLeaseFactory()))

    def build_setup_commands(self):
        from .program_manager.interactors.setup_command import RunSetupCommandInteractor
        return RunSetupCommandInteractor(self, HostOwnershipInteractor(HostLeaseFactory()))

    def build_program_runner(self):
        from .program_manager.interactors.command import ProgramRunInteractor

        from .program_manager.interactors.compilation import CompilationInteractor
        return ProgramRunInteractor(self, DriverLoaderInteractor(), CompilationInteractor(), HostOwnershipInteractor(HostLeaseFactory()))


class LanguageProgramExecutorFactory:
    def build(self):
        from .program_manager.interactors.language_entry import (
            LanguageProgramInteractor,
        )

        return LanguageProgramInteractor(OSApplicationFactory().build_program_runner())


class HostLeaseFactory:
    def build(self, context, socket_path=None):
        from .lifecycle_manager.repository import LocalHostLeaseRepository
        from .lifecycle_manager.interactors import HostLeasePathInteractor
        return LocalHostLeaseRepository(HostLeasePathInteractor().paths(context, socket_path))



class ResidentWorkerFactory:
    def __init__(self, applications):
        self.applications = applications

    def build(self, context, status):
        from .program_manager.repositories.queue import SqliteRunQueueRepository
        from .program_manager.interactors.resident import ResidentWorkerInteractor
        application = self.applications.build(context)
        connection = DatabaseConnection(context.database_path).open()
        return ResidentWorkerInteractor(application, SqliteRunQueueRepository(connection), connection, status)


class ResidentCommandFactory:
    def __init__(self, applications):
        self.applications = applications

    def build(self, context, status, configuration):
        from .program_manager.repositories.queue import SqliteRunQueueRepository
        from .program_manager.interactors.compilation import CompilationInteractor
        from .program_manager.interactors.resident import ResidentCommandInteractor
        inspector = self.applications.build_run_inspector(context)
        queue = SqliteRunQueueRepository(inspector.tasks.repository.connection)
        from .program_manager.repositories.setup import SqliteRunSetupRepository
        from .program_manager.interactors.setup import RunSetupRequestInteractor
        setup_requests = RunSetupRequestInteractor(SqliteRunSetupRepository(inspector.tasks.repository.connection), inspector.tasks)
        return ResidentCommandInteractor(CompilationInteractor(),inspector.tasks,queue,inspector,
            HostedRuntimeInteractor(),RuntimeCheckpointCodecInteractor(),status,context,
            self.applications.build_device_inspector(context),configuration,setup_requests)
