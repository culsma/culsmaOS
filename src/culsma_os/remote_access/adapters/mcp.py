"""Read-only MCP entry for a remote station with an injected transport."""
from functools import wraps
from typing import Any

from culsma_os.auth.models import ConsoleAccessError
from culsma_os.program_manager.models import ConsoleReadError
from .client import RemoteStationClient


class RemoteMCPServerAdapter:
    def __init__(self, client: RemoteStationClient):
        self.client = client

    def make_server(self):
        from mcp.server.mcpserver import MCPServer
        from mcp.types import ToolAnnotations

        server = MCPServer('culsmaOS-remote', instructions=(
            'Read one explicitly configured remote CulsmaOS station. '
            'Only station status and existing run observations are exposed. '
            'No experiment submission, device execution or local fallback. '
            'This entry requires an authenticated transport supplied by the host.'))
        for method, description in [
            (self.station_status, 'Read the configured remote station status.'),
            (self.list_runs, 'List runs on the configured remote station.'),
            (self.run_status, 'Read an existing remote run and its execution evidence.'),
        ]:
            server.tool(name=method.__name__, description=description,
                        structured_output=True, annotations=ToolAnnotations(
                            readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=False))(
                                self.tool_function(method))
        return server

    def serve(self):
        """Serve tools over the MCP client's stdio connection."""
        self.make_server().run(transport='stdio')

    def tool_function(self, method):
        from mcp.server.mcpserver.exceptions import ToolError

        @wraps(method)
        def call(*args, **kwargs):
            try:
                return method(*args, **kwargs)
            except (ConsoleAccessError, ConsoleReadError) as error:
                raise ToolError(f'{error.code} ({error.kind})') from None
            except OSError:
                # Transport exceptions can contain URLs or credentials.
                raise ToolError('REMOTE_CONNECTION_UNAVAILABLE') from None
            except ValueError:
                raise ToolError('REMOTE_READ_REQUEST_INVALID') from None
        return call

    def station_status(self) -> dict[str, Any]:
        return self.client.station_status()

    def list_runs(self) -> dict[str, Any]:
        return self.client.list_runs()

    def run_status(self, run_id: str) -> dict[str, Any]:
        return self.client.run_status(run_id)
