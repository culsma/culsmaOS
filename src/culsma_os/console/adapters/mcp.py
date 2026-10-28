"""MCP stdio adapter: DTO mapping only; all actions enter authorized Interactors."""
from typing import Any, Literal
from culsma_os.resource_manager.models import SupplyReplacementRequest
from culsma_os.console_interaction.models import ViewStateReadRequest, ViewRequest
from culsma_os.program_manager.models import SetupInteractionRequest, ConsoleProgramRequest, ConsoleReadRequest


class MCPServerAdapter:
    def __init__(self, setup, programs, observation, view_reads=None, view_requests=None, supplies=None):
        self.setup, self.programs, self.observation = setup, programs, observation
        self.view_reads, self.view_requests = view_reads, view_requests
        self.supplies = supplies

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
            (self.list_programs, True, 'List protocol files and their source directory in the configured program root or Culsma Home.'),
            (self.preview_program, True, 'Preview experiment requirements against the current station without creating a run or reserving resources.'),
            (self.inspect_program, True, 'Inspect and freeze a program source snapshot before submission.'),
            (self.start_program, False, 'Start a reviewed program; preparation and simulation loading advance automatically. Physical loading still requires an operator.'),
            (self.submit_program, False, 'Submit a reviewed program snapshot to the existing OS queue.'),
            (self.control_request_status, True, 'Read the original control request receipt; acknowledgement does not establish application.'),
            (self.control_run, False, 'Request pause, resume or cancellation at an OS execution boundary.'),
        ]:
            server.tool(name=method.__name__, description=description, structured_output=True,
                annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=not read_only,
                                            idempotentHint=read_only, openWorldHint=False))(method)
        if self.view_reads is not None and self.view_requests is not None:
            for method, read_only, description in [
                (self.view_state, True, 'Read renderer-reported console sessions, view state, epochs and revisions; this is not physical evidence.'),
                (self.view_request_status, True, 'Read whether a view request was accepted, displayed, deferred, rejected or expired. Displayed is a renderer report.'),
                (self.open_view, False, 'Request a console view on an explicit live session and epoch. Accepted does not mean displayed; no experiment is started.'),
                (self.reveal_entity, False, 'Request focus/highlight of a declared workstation entity; no labware or material is changed.'),
            ]:
                server.tool(name=method.__name__, description=description, structured_output=True,
                    annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=False,
                        idempotentHint=True, openWorldHint=False))(method)
        if self.supplies is not None:
            for method,readonly in [(self.tip_supply,True),(self.replace_simulated_tip_box,False),(self.tip_replacement_status,True)]:
                server.tool(name=method.__name__,structured_output=True,
                    annotations=ToolAnnotations(readOnlyHint=readonly,destructiveHint=not readonly,idempotentHint=True,openWorldHint=False))(method)
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

    def preview_program(self, program_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('preview', program_id))

    def submit_program(self, program_id: str, snapshot_id: str, request_id: str,
                       configuration_fingerprint: str | None = None) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('submit', program_id, snapshot_id,
            request_id, configuration_fingerprint=configuration_fingerprint))

    def start_program(self, program_id: str, snapshot_id: str, request_id: str,
                      configuration_fingerprint: str | None = None) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('start', program_id, snapshot_id,
            request_id, configuration_fingerprint=configuration_fingerprint))

    def control_run(self, run_id: str, action: Literal['pause','resume','cancel'], request_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest(action, request_id=request_id, run_id=run_id))

    def control_request_status(self, run_id: str, request_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('control-status', request_id=request_id, run_id=run_id))

    def view_state(self) -> dict[str, Any]:
        return self.view_reads.execute(self.raw_credential, ViewStateReadRequest())

    def view_request_status(self, request_id: str) -> dict[str, Any]:
        return self.view_reads.execute(self.raw_credential, ViewStateReadRequest('receipt', request_id))

    def open_view(self, session_id: str, epoch: str, expected_revision: int, request_id: str,
                  view: Literal['experiment','workstation','files','settings','system_info'],
                  entity_id: str | None = None) -> dict[str, Any]:
        return self.view_requests.execute(self.raw_credential,
            ViewRequest('open', request_id, session_id, epoch, expected_revision, view, entity_id))

    def reveal_entity(self, session_id: str, epoch: str, expected_revision: int,
                      request_id: str, entity_id: str) -> dict[str, Any]:
        return self.view_requests.execute(self.raw_credential,
            ViewRequest('reveal', request_id, session_id, epoch, expected_revision, 'workstation', entity_id))

    def tip_supply(self) -> dict[str,Any]:
        """Read declared tip positions, current simulated load and replacement history."""
        return self.supplies.execute(self.raw_credential,SupplyReplacementRequest())

    def replace_simulated_tip_box(self,request_id:str,expected_revision:str,resource_id:str,
                                 positions:list[str],simulation_acknowledged:bool) -> dict[str,Any]:
        """Explicitly declare a new simulated box. Never confirms physical loading; poll the receipt."""
        return self.supplies.execute(self.raw_credential,SupplyReplacementRequest('replace',request_id,expected_revision,
            resource_id,positions,simulation_acknowledged))

    def tip_replacement_status(self,request_id:str) -> dict[str,Any]:
        """Reconcile the original receipt without reissuing inventory changes."""
        return self.supplies.execute(self.raw_credential,SupplyReplacementRequest('status',request_id))
