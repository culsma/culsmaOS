"""Composition only; no device execution worker or live configuration changes."""
from pathlib import Path
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.interactors.console_session import ConsoleSessionInteractor
from culsma_os.workspace_manager.interactors import StationConfigurationInteractor, ProgramBindingInteractor
from culsma_os.workspace_manager.repositories.configuration import SqliteStationConfigurationRepository
from culsma_os.device_manager.interactors import DeviceProfileInteractor
from culsma_os.driver_framework.interactors import DriverProfileInteractor
from culsma_os.program_manager.interactors.console_program import ConsoleProgramInteractor
from culsma_os.program_manager.interactors.source import ProgramSourceInteractor
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
from .adapters.http import ConsoleHTTPServer


class ConsoleApplicationFactory:
    def build(self, settings):
        tokens = TokenInteractor(SessionCredentialRepository())
        repository = SqliteStationConfigurationRepository(settings.drafts_path or Path('run-artifacts/console/drafts.sqlite3'))
        profiles = DeviceProfileInteractor(DriverProfileInteractor())
        source = ProgramSourceInteractor(FileProgramSourceRepository(settings.program_root,
            settings.program_store or Path('run-artifacts/console/programs')),CompilationInteractor(),HostedRuntimeInteractor())
        return ConsoleHTTPServer(settings, ConsoleCommandInteractor(ResidentClientAdapter(settings.socket_path,timeout=3)),
            StationConfigurationInteractor(tokens,repository,profiles),ConsoleSessionInteractor(tokens),
            ConsoleProgramInteractor(tokens,source,ResidentClientAdapter(settings.socket_path,timeout=10)),
            ProgramBindingInteractor(tokens,repository,profiles,source))
