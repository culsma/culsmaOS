"""Composition only; no device execution worker or live configuration changes."""
from pathlib import Path
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.interactors.console_session import ConsoleSessionInteractor
from culsma_os.workspace_manager.interactors import StationConfigurationInteractor
from culsma_os.workspace_manager.repositories.configuration import SqliteStationConfigurationRepository
from culsma_os.device_manager.interactors import DeviceProfileInteractor
from culsma_os.driver_framework.interactors import DriverProfileInteractor
from .adapters.http import ConsoleHTTPServer


class ConsoleApplicationFactory:
    def build(self, settings):
        tokens = TokenInteractor(SessionCredentialRepository())
        return ConsoleHTTPServer(settings, ConsoleCommandInteractor(
            ResidentClientAdapter(settings.socket_path, timeout=3)),
            StationConfigurationInteractor(tokens,SqliteStationConfigurationRepository(
                settings.drafts_path or Path('run-artifacts/console/drafts.sqlite3')),DeviceProfileInteractor(DriverProfileInteractor())),
            ConsoleSessionInteractor(tokens))
