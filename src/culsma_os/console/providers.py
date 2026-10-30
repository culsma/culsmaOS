"""Composition only; device workers and configuration application stay resident-owned."""
from pathlib import Path
import hashlib
from culsma_os.console_interaction.interactors import ViewStateReadInteractor, ViewRequestInteractor, RendererSessionInteractor
from culsma_os.console_interaction.repository import SqliteViewInteractionRepository
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.interactors.console_session import ConsoleSessionInteractor
from culsma_os.workspace_manager.interactors import StationConfigurationInteractor, ProgramBindingInteractor, ConfigurationDraftInteractor
from culsma_os.workspace_manager.repositories.configuration import SqliteStationConfigurationRepository
from culsma_os.device_manager.interactors import DeviceProfileInteractor
from culsma_os.driver_framework.interactors import DriverProfileInteractor
from culsma_os.program_manager.interactors.console_program import ConsoleProgramInteractor
from culsma_os.program_manager.interactors.source import ProgramSourceInteractor
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
from culsma_os.lifecycle_manager.interactors import ConsoleActivationInteractor
from .adapters.http import ConsoleHTTPServer
from culsma_os.program_manager.interactors.setup_interaction import SetupInteractionInteractor, SetupConfirmationInteractor, AutomationObservationInteractor


class ConsoleApplicationFactory:
    def build_view_interaction(self, settings, tokens, observation, documents=None):
        path = settings.view_store_path or settings.socket_path.with_name(settings.socket_path.name + '.views.sqlite3')
        station_id = hashlib.sha256(str(settings.socket_path.resolve()).encode()).hexdigest()
        repository = SqliteViewInteractionRepository(path, station_id)
        return (ViewStateReadInteractor(tokens, repository),
                ViewRequestInteractor(tokens, repository, observation, documents=documents),
                RendererSessionInteractor(tokens, repository))

    def build_desktop(self, settings, executable, resident_command=None, log_path=None):
        from .interactors import ConsoleApplicationLifecycleInteractor
        from .adapters.desktop import NativeConsoleProcessAdapter, ResidentProcessAdapter
        from dataclasses import replace
        server = self.build(replace(settings,serve_frontend=False))
        return ConsoleApplicationLifecycleInteractor(server, server.sessions, NativeConsoleProcessAdapter(executable),
            ResidentProcessAdapter(resident_command, log_path, Path(log_path).parent/'stations') if resident_command else None)

    def installation_root(self,settings):
        from culsma_os.file_system.interactors import UserWorkspaceRootInteractor
        return settings.file_root or UserWorkspaceRootInteractor().resolve(settings.home_path)

    def installation_source(self,settings):
        return ProgramSourceInteractor(FileProgramSourceRepository(self.installation_root(settings),
            (settings.program_store or Path('run-artifacts/console/programs'))/'installation',selected_only=True),
            CompilationInteractor(),HostedRuntimeInteractor(),selected_only=True)

    def build_document_query(self,source):
        from culsma_os.file_system.interactors import DocumentInspectionInteractor
        from culsma_os.file_system.repository import LocalFileWorkspaceRepository
        return DocumentInspectionInteractor(LocalFileWorkspaceRepository(source.sources.root)) if source.sources.root is not None else None

    def build_workspace(self,tokens,source):
        from culsma_os.file_system.interactors import FileWorkspaceInteractor
        from culsma_os.file_system.repository import LocalFileWorkspaceRepository
        return FileWorkspaceInteractor(tokens,LocalFileWorkspaceRepository(source.sources.root)) if source.sources.root is not None else None

    def build_files(self,settings,tokens,source):
        from culsma_os.file_system.interactors import FileReadInteractor
        from culsma_os.file_system.repository import LocalFileReadRepository
        return FileReadInteractor(tokens,LocalFileReadRepository({'installation':self.installation_root(settings),
            'programs':source.sources.root},(source.sources.store,),home=self.installation_root(settings)),source.sources.root)

    def build(self, settings):
        tokens = TokenInteractor(SessionCredentialRepository())
        repository = SqliteStationConfigurationRepository(settings.drafts_path or Path('run-artifacts/console/drafts.sqlite3'))
        profiles = DeviceProfileInteractor(DriverProfileInteractor())
        source = ProgramSourceInteractor(FileProgramSourceRepository(settings.program_root,
            settings.program_store or Path('run-artifacts/console/programs'), settings.home_path),CompilationInteractor(),HostedRuntimeInteractor())
        from culsma_os.workspace_manager.interactors import LabwareConfigurationInteractor
        from culsma_os.resource_manager.interactors import SupplyInteractionInteractor
        from culsma_os.developer_tools.interactors import DeveloperTestInteractor
        return ConsoleHTTPServer(settings, ConsoleCommandInteractor(ResidentClientAdapter(settings.socket_path,timeout=3)),
            StationConfigurationInteractor(tokens,repository,profiles),ConsoleSessionInteractor(tokens),
            ConsoleProgramInteractor(tokens,source,ResidentClientAdapter(settings.socket_path,timeout=10),{"installation":self.installation_source(settings)}),
            ProgramBindingInteractor(tokens,repository,profiles,source),
            ConsoleActivationInteractor(tokens,ConfigurationDraftInteractor(repository,profiles),ResidentClientAdapter(settings.socket_path,timeout=10)),
            SetupInteractionInteractor(tokens,ResidentClientAdapter(settings.socket_path,timeout=10)),
            SetupConfirmationInteractor(tokens,ResidentClientAdapter(settings.socket_path,timeout=10)),
            LabwareConfigurationInteractor(tokens,repository,ResidentClientAdapter(settings.socket_path,timeout=10)),
            *self.build_view_interaction(settings,tokens,ConsoleCommandInteractor(ResidentClientAdapter(settings.socket_path,timeout=3)), self.build_document_query(source)),
            supplies=SupplyInteractionInteractor(tokens,ResidentClientAdapter(settings.socket_path,timeout=10)),
            file_reads=self.build_files(settings,tokens,source),
            file_workspace=self.build_workspace(tokens,source),
            developer_tests=DeveloperTestInteractor(tokens,ResidentClientAdapter(settings.socket_path,timeout=10)))

    def build_mcp(self, settings):
        from .adapters.mcp import MCPServerAdapter
        from .interactors import MCPHostInteractor
        tokens = TokenInteractor(SessionCredentialRepository())
        resident = ResidentClientAdapter(settings.socket_path, timeout=10)
        source = ProgramSourceInteractor(FileProgramSourceRepository(settings.program_root,
            settings.program_store or Path('run-artifacts/console/programs'), settings.home_path), CompilationInteractor(), HostedRuntimeInteractor())
        view_reads, view_requests, _ = self.build_view_interaction(settings,tokens,ConsoleCommandInteractor(resident),self.build_document_query(source))
        from culsma_os.resource_manager.interactors import SupplyInteractionInteractor
        bridge = MCPServerAdapter(SetupInteractionInteractor(tokens,resident),
            ConsoleProgramInteractor(tokens,source,resident,{"installation":self.installation_source(settings)}),
            AutomationObservationInteractor(tokens,ConsoleCommandInteractor(resident)),view_reads,view_requests,SupplyInteractionInteractor(tokens,resident),self.build_files(settings,tokens,source),file_workspace=self.build_workspace(tokens,source))
        return MCPHostInteractor(tokens,bridge)
