"""Explicit composition for the remote MCP client and station read service."""
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from .adapters.http import RemoteReadHTTPServer, RemoteReadRequestAdapter
from .adapters.client import RemoteStationClient
from .adapters.identity import FileRemoteIdentityAdapter
from .adapters.mcp import RemoteMCPServerAdapter
from .adapters.transport import RemoteHTTPTransport
from .interactors import RemoteReadInteractor
from .models import RemoteAccessSettings, RemoteConnectionMode
from .ports import RemoteIdentityPort, RemoteReadTransportPort


class RemoteAccessFactory:
    def build_transport(self, endpoint, token_file, *, mode=None,
                        access_token_file=None) -> RemoteReadTransportPort:
        # Preserve configurations written before the connection flag existed.
        if mode is None and access_token_file is not None:
            mode = RemoteConnectionMode.CLOUDFLARE
        if mode is not None:
            mode = RemoteConnectionMode(mode)
        if mode is RemoteConnectionMode.CLOUDFLARE:
            from .adapters.cloudflare import CloudflareAccessTransport

            if access_token_file is None:
                raise ValueError('cloudflare requires --access-token-file')
            return CloudflareAccessTransport(endpoint, token_file, access_token_file)
        if access_token_file is not None:
            raise ValueError('--access-token-file requires the cloudflare connection')

        transport = RemoteHTTPTransport(endpoint, token_file)
        if mode is RemoteConnectionMode.TUNNEL and transport.address.scheme != 'http':
            raise ValueError('tunnel requires a loopback HTTP URL')
        if mode is RemoteConnectionMode.HTTPS and transport.address.scheme != 'https':
            raise ValueError('https requires an HTTPS URL')
        return transport

    def build_mcp(self, station_id: str, transport: RemoteReadTransportPort):
        """AI-side entry; a real authenticated transport must be supplied."""
        RemoteAccessSettings(station_id)  # Validate configuration, not a tool argument.
        return RemoteMCPServerAdapter(RemoteStationClient(station_id, transport))

    def build_read_adapter(self, settings: RemoteAccessSettings,
                           identity: RemoteIdentityPort, socket_path):
        # Local endpoint credentials remain on the instrument computer.
        observation = ConsoleCommandInteractor(ResidentClientAdapter(socket_path, timeout=10))
        return RemoteReadRequestAdapter(RemoteReadInteractor(settings, identity, observation))

    def build_read_server(self, station_id, grants, socket_path, port):
        settings = RemoteAccessSettings(station_id, enabled=True)
        identity = FileRemoteIdentityAdapter(grants, station_id)
        return RemoteReadHTTPServer(port, self.build_read_adapter(settings, identity, socket_path))
