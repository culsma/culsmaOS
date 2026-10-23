"""MCP stdio adapter: DTO mapping only; all actions enter authorized Interactors."""
from typing import Any, Literal
from culsma_os.program_manager.models import SetupInteractionRequest, ConsoleProgramRequest, ConsoleReadRequest


class MCPServerAdapter:
    def __init__(self, setup, programs, observation):
        self.setup, self.programs, self.observation = setup, programs, observation

    def make_server(self, raw_credential):
        from mcp.server.mcpserver import MCPServer
        from mcp.types import ToolAnnotations
        self.raw_credential = raw_credential
        server = MCPServer('culsmaOS', instructions=(
            'Operate the existing local OS resident. Commands return durable request receipts; '
            'poll their status before claiming application. Read the latest loading plan before editing; '
            'include its fingerprint. Physical loading confirmation belongs to the operator console '
            'and is not an MCP tool. Declared layout and material are not sensor observations.'))
        for method, read_only, description in [
            (self.station_status, True, 'Read station, device and run observations.'),
            (self.list_runs, True, 'List current resident runs.'),
            (self.run_status, True, 'Read a run, its OS report and execution evidence.'),
            (self.loading_plan, True, 'Read the current loading plan, physical checklist and shared operation history.'),
            (self.revise_loading_plan, False, 'Revise the exact loading plan using fixed or preferred allocation addresses; confirmation is invalidated.'),
            (self.begin_loading, False, 'Reserve the station for loading. This does not confirm that physical loading occurred.'),
            (self.loading_request_status, True, 'Read a durable loading command receipt; pending is not application.'),
            (self.list_programs, True, 'List programs inside the explicitly configured program root.'),
            (self.inspect_program, True, 'Inspect and freeze a program source snapshot before submission.'),
            (self.submit_program, False, 'Submit a reviewed program snapshot to the existing OS queue.'),
            (self.control_run, False, 'Request pause, resume or cancellation at an OS execution boundary.'),
        ]:
            server.tool(name=method.__name__, description=description, structured_output=True,
                annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=not read_only,
                                            idempotentHint=read_only, openWorldHint=False))(method)
        return server

    def serve(self, raw_credential):
        self.make_server(raw_credential).run(transport='stdio')

    def station_status(self) -> dict[str, Any]:
        return self.observation.execute(self.raw_credential, ConsoleReadRequest('station'))

    def list_runs(self) -> dict[str, Any]:
        return self.observation.execute(self.raw_credential, ConsoleReadRequest('runs'))

    def run_status(self, run_id: str) -> dict[str, Any]:
        return self.observation.execute(self.raw_credential, ConsoleReadRequest('run', run_id))

    def loading_plan(self, run_id: str) -> dict[str, Any]:
        return self.setup.execute(self.raw_credential, SetupInteractionRequest('show', run_id))

    def revise_loading_plan(self, run_id: str, fingerprint: str, request_id: str,
                            fixed: dict[str, dict[str, str]] | None = None,
                            preferred: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
        return self.setup.execute(self.raw_credential, SetupInteractionRequest('revise', run_id,
            request_id, fingerprint, {'fixed': fixed or {}, 'preferred': preferred or {}}))

    def begin_loading(self, run_id: str, fingerprint: str, request_id: str) -> dict[str, Any]:
        return self.setup.execute(self.raw_credential, SetupInteractionRequest('begin', run_id, request_id, fingerprint))

    def loading_request_status(self, run_id: str, request_id: str) -> dict[str, Any]:
        return self.setup.execute(self.raw_credential, SetupInteractionRequest('status', run_id, request_id))

    def list_programs(self) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('list'))

    def inspect_program(self, program_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('inspect', program_id))

    def submit_program(self, program_id: str, snapshot_id: str, request_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('submit', program_id, snapshot_id, request_id))

    def control_run(self, run_id: str, action: Literal['pause','resume','cancel'], request_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest(action, request_id=request_id, run_id=run_id))
