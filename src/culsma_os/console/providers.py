"""Composition only; device workers and configuration application stay resident-owned."""
from pathlib import Path
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
    def build_desktop(self, settings, executable, resident_command=None, log_path=None):
        from .interactors import DesktopConsoleInteractor
        from .adapters.desktop import NativeConsoleProcessAdapter, ResidentProcessAdapter
        server = self.build(settings)
        return DesktopConsoleInteractor(server, server.sessions, NativeConsoleProcessAdapter(executable),
            ResidentProcessAdapter(resident_command, log_path, Path(log_path).parent/'stations') if resident_command else None)

    def build(self, settings):
        tokens = TokenInteractor(SessionCredentialRepository())
        repository = SqliteStationConfigurationRepository(settings.drafts_path or Path('run-artifacts/console/drafts.sqlite3'))
        profiles = DeviceProfileInteractor(DriverProfileInteractor())
        source = ProgramSourceInteractor(FileProgramSourceRepository(settings.program_root,
            settings.program_store or Path('run-artifacts/console/programs')),CompilationInteractor(),HostedRuntimeInteractor())
        return ConsoleHTTPServer(settings, ConsoleCommandInteractor(ResidentClientAdapter(settings.socket_path,timeout=3)),
            StationConfigurationInteractor(tokens,repository,profiles),ConsoleSessionInteractor(tokens),
            ConsoleProgramInteractor(tokens,source,ResidentClientAdapter(settings.socket_path,timeout=10)),
            ProgramBindingInteractor(tokens,repository,profiles,source),
            ConsoleActivationInteractor(tokens,ConfigurationDraftInteractor(repository,profiles),ResidentClientAdapter(settings.socket_path,timeout=10)),
            SetupInteractionInteractor(tokens,ResidentClientAdapter(settings.socket_path,timeout=10)),
            SetupConfirmationInteractor(tokens,ResidentClientAdapter(settings.socket_path,timeout=10)))

    def build_mcp(self, settings):
        from .adapters.mcp import MCPServerAdapter
        from .interactors import MCPHostInteractor
        tokens = TokenInteractor(SessionCredentialRepository())
        resident = ResidentClientAdapter(settings.socket_path, timeout=10)
        source = ProgramSourceInteractor(FileProgramSourceRepository(settings.program_root,
            settings.program_store or Path('run-artifacts/console/programs')), CompilationInteractor(), HostedRuntimeInteractor())
        bridge = MCPServerAdapter(SetupInteractionInteractor(tokens,resident),
            ConsoleProgramInteractor(tokens,source,resident),
            AutomationObservationInteractor(tokens,ConsoleCommandInteractor(resident)))
        return MCPHostInteractor(tokens,bridge)
