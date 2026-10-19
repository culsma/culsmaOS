"""Compose the read-only console without building an execution application."""
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from .adapters.http import ConsoleHTTPServer


class ConsoleApplicationFactory:
    def build(self, settings):
        return ConsoleHTTPServer(settings, ConsoleCommandInteractor(
            ResidentClientAdapter(settings.socket_path, timeout=3)))
