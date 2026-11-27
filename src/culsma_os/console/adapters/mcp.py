"""MCP stdio adapter: DTO mapping only; all actions enter authorized Interactors."""
from typing import Any, Literal
from functools import wraps
from .settings_mcp import MCPSettingsTools
from .instrument_profiles import MCPInstrumentProfileTools
from culsma_os.device_manager.instruments.models import ModuleProfileError
from culsma_os.device_manager.models import DeviceProfileQueryError
from culsma_os.workspace_manager.models import ConfigurationError
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.lifecycle_manager.models import StationSelectionError
from culsma_os.file_system.models import FileReadError
from culsma_os.console_interaction.models import ViewInteractionError
from culsma_os.program_manager.models import ConsoleReadError, ConsoleProgramError
from culsma_os.resource_manager.models import SupplyReplacementError
from culsma_os.resource_manager.models import SupplyReplacementRequest
from culsma_os.file_system.models import FileReadRequest
from culsma_os.console_interaction.models import ViewStateReadRequest, ViewRequest
from culsma_os.program_manager.models import SetupInteractionRequest, ConsoleProgramRequest, ConsoleReadRequest


class MCPServerAdapter(MCPSettingsTools, MCPInstrumentProfileTools):
    def __init__(self, setup, programs, observation, view_reads=None, view_requests=None, supplies=None, file_reads=None, file_workspace=None, configuration=None, bindings=None, activation=None, labware=None, developer_tests=None, station_selection=None, instrument_profiles=None, workflow_simulation=None, station_service=None, setup_confirmation=None):
        self.setup_confirmation = setup_confirmation
        self.station_service = station_service
        self.workflow_simulation = workflow_simulation
        self.instrument_profiles = instrument_profiles
        self.station_selection = station_selection
        self.setup, self.programs, self.observation = setup, programs, observation
        self.configuration, self.bindings, self.activation = configuration, bindings, activation
        self.labware, self.developer_tests = labware, developer_tests
        self.view_reads, self.view_requests = view_reads, view_requests
        self.file_workspace=file_workspace
        self.file_reads=file_reads
        self.supplies = supplies

    def make_server(self, raw_credential):
        from mcp.server.mcpserver import MCPServer
        from mcp.types import ToolAnnotations
        self.raw_credential = raw_credential
        # The SDK normally discards unknown arguments during input validation.
        class ProgramRequestServer(MCPServer):
            async def call_tool(self, name, arguments, context=None):
                if name in ('preview_program', 'prepare_program', 'submit_program', 'start_program') and 'profile_bindings' in arguments:
                    from mcp.server.mcpserver.exceptions import ToolError
                    raise ToolError('PROFILE_RUN_BINDINGS_RETIRED')
                return await super().call_tool(name, arguments, context)

        server = ProgramRequestServer('culsmaOS', instructions=(
            'Operate the existing local OS resident. When available, station_selection_status and select_station_for_next_start choose a product workstation for the next App start; they do not hot-switch a running driver. Restart the App and reconnect MCP when indicated, then verify station_status. Authorized file/configuration operations appear in the native console activity and refresh saved content; unsaved operator edits are retained. view_state includes recent presentation activity, not device execution evidence. Read station_status.data.host.capabilities before optional driver operations. Tool visibility does not imply driver support. Commands return durable request receipts; '
            'poll their status before claiming application. Read the latest loading plan before editing; '
            'include its fingerprint. Use prepare_program to create a loading preparation, then show the experiment view on the host console. '
            'Preparation is not execution submission. After the operator confirms the exact loading plan and authorizes execution, '
            'confirm_loading can submit it for execution without another console click. '
            'Declared layout and material are not sensor observations.'))
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
            (self.prepare_program, False, 'Create a loading preparation for a reviewed snapshot. Does not submit for execution or automatically confirm loading, including in simulation.'),
            (self.start_program, False, 'Start a reviewed program; preparation and simulation loading advance automatically. Physical loading still requires an operator.'),
            (self.submit_program, False, 'Submit a reviewed program snapshot to the existing OS queue.'),
            (self.control_request_status, True, 'Read the original control request receipt; acknowledgement does not establish application.'),
            (self.control_run, False, 'Request pause, resume or cancellation at an OS execution boundary.'),
        ]:
            server.tool(name=method.__name__, description=description, structured_output=True,
                annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=not read_only,
                                            idempotentHint=read_only, openWorldHint=False))(self.tool_function(method))
        if self.setup_confirmation is not None:
            server.tool(name='confirm_loading', description=self.confirm_loading.__doc__, structured_output=True,
                annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                    idempotentHint=True, openWorldHint=False))(self.tool_function(self.confirm_loading))
        if self.station_service is not None:
            for method, readonly in ((self.describe_station_service, True),
                                     (self.set_native_debug, False),
                                     (self.debug_prepare_native_method, False),
                                     (self.debug_execute_native_method, False),
                                     (self.native_method_logs, True),
                                     (self.run_logs, True),
                                     (self.initialize_station, False),
                                     (self.station_service_status, True),
                                     (self.cancel_station_service, False),
                                     (self.physical_execution_status, True),
                                     (self.set_physical_execution, False)):
                server.tool(name=method.__name__, description=method.__doc__, structured_output=True,
                    annotations=ToolAnnotations(readOnlyHint=readonly, destructiveHint=not readonly,
                        idempotentHint=True, openWorldHint=False))(self.tool_function(method))
        if self.file_workspace is not None:
            for method in (self.read_document,self.create_document,self.save_document,self.receive_files):
                server.tool(name=method.__name__,description=method.__doc__,structured_output=True,
                    annotations=ToolAnnotations(readOnlyHint=method==self.read_document,
                        destructiveHint=method!=self.read_document,idempotentHint=method==self.read_document,
                        openWorldHint=False))(self.tool_function(method))
        if self.view_reads is not None and self.view_requests is not None:
            for method, read_only, description in [
                (self.view_state, True, 'Read renderer-reported console sessions, view state, epochs and revisions; this is not physical evidence.'),
                (self.view_request_status, True, 'Read whether a view request was accepted, displayed, deferred, rejected or expired. Displayed is a renderer report.'),
                (self.open_view, False, 'Request a console view on an explicit live session and epoch. Accepted does not mean displayed; no experiment is started.'),
                (self.reveal_entity, False, 'Request focus/highlight of a declared workstation entity; no labware or material is changed.'),
            ]:
                server.tool(name=method.__name__, description=description, structured_output=True,
                    annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=False,
                        idempotentHint=True, openWorldHint=False))(self.tool_function(method))
        if self.supplies is not None:
            for method,readonly in [(self.tip_supply,True),(self.replace_simulated_tip_box,False),(self.tip_replacement_status,True)]:
                server.tool(name=method.__name__,structured_output=True,
                    annotations=ToolAnnotations(readOnlyHint=readonly,destructiveHint=not readonly,idempotentHint=True,openWorldHint=False))(self.tool_function(method))
        if self.file_reads is not None:
            for method in [self.file_roots,self.list_directory,self.preview_file]:
                server.tool(name=method.__name__,structured_output=True,annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False))(self.tool_function(method))
        for method, readonly in self.settings_tools():
            server.tool(name=method.__name__, description=method.__doc__, structured_output=True,
                annotations=ToolAnnotations(readOnlyHint=readonly, destructiveHint=not readonly,
                    idempotentHint=readonly, openWorldHint=False))(self.tool_function(method))
        return server

    def tool_function(self, method):
        """Map known use-case failures to deliberate MCP errors without exposing internals."""
        from mcp.server.mcpserver.exceptions import ToolError
        @wraps(method)
        def call(*args, **kwargs):
            try:
                return method(*args, **kwargs)
            except (ConsoleAccessError, StationSelectionError, FileReadError, ViewInteractionError,
                    ConsoleReadError, ConsoleProgramError, SupplyReplacementError, ConfigurationError, DeviceProfileQueryError, ModuleProfileError) as error:
                raise ToolError(f'{error.code} ({error.kind})') from None
        return call

    def serve(self, raw_credential):
        self.make_server(raw_credential).run(transport='stdio')

    def station_status(self) -> dict[str, Any]:
        return self.observation.execute(self.raw_credential, ConsoleReadRequest('station'))

    def physical_execution_status(self) -> dict[str, Any]:
        """Read whether the station Agent permits physical execution."""
        return self.station_service.execute(self.raw_credential, {'action': 'physical-permission-status'})

    def set_physical_execution(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable physical execution on the idle station Agent. Does not select a mode or start hardware."""
        return self.station_service.execute(self.raw_credential, {
            'action': 'set-physical-permission', 'enabled': enabled})

    def describe_station_service(self) -> dict[str, Any]:
        """Read driver initialization, native maintenance capabilities and unresolved requests. Does not move hardware."""
        return self.station_service.execute(self.raw_credential, {'action': 'describe'})

    def set_native_debug(self, enabled: bool) -> dict[str, Any]:
        """Toggle native troubleshooting for this running station. Read back via describe_station_service.
        Use on explicit request for debugging. The switch does not dispatch a method or grant physical execution.
        """
        return self.station_service.execute(self.raw_credential, {'action': 'set-native-debug', 'enabled': enabled})

    def debug_prepare_native_method(self, entrypoint: str, files: list[dict[str, str]],
                              mode: Literal['simulation', 'physical'], debug_reason: str) -> dict[str, Any]:
        """Troubleshooting only. Record a concrete fault or diagnostic question. Use prepare_program for experiments.

        Stage a developer-authored native method bundle on the station; never execute it.

        Read describe_station_service for the installed driver's supported format and requirements.
        Send files as {path: relative path, data_base64: exact bytes}; the driver validates them.
        Retain returned method_id, bundle_sha256 and mode. This is packaging, not vendor validation.
        Follow the driver's completion contract; native execution does not update experiment inventory.
        """
        return self.station_service.execute(self.raw_credential, {
            'action': 'prepare-native', 'entrypoint': entrypoint, 'files': files, 'mode': mode, 'debug_reason': debug_reason})

    def debug_execute_native_method(self, request_id: str, method_id: str, bundle_sha256: str,
                              mode: Literal['simulation', 'physical'], debug_reason: str, acknowledge_clearance: bool = False) -> dict[str, Any]:
        """Troubleshooting only. Use prepare_program and confirm_loading for experiments.

        Execute an exact prepared developer method using the installed driver's lifecycle.

        Physical mode can move hardware and requires operator clearance. Simulation is explicit.
        Preserve request_id; query station_service_status after a timeout, never replay with a new ID.
        Native completion is not proof of transferred volume and does not update experiment inventory.
        Cancel through cancel_station_service; it confirms release only when the vendor is idle.
        """
        return self.station_service.execute(self.raw_credential, {
            'action': 'execute-native', 'request_id': request_id, 'method_id': method_id,
            'bundle_sha256': bundle_sha256, 'mode': mode, 'acknowledge_clearance': acknowledge_clearance, 'debug_reason': debug_reason})

    def native_method_logs(self, request_id: str, offset: int = 0, limit: int = 65536,
                           stream: Literal['receipt', 'trace'] = 'receipt') -> dict[str, Any]:
        """Read bounded base64 native receipt or captured vendor trace, using byte cursors.

        Read content formats and encodings from describe_station_service. Captured output may be pending.
        Reading logs never dispatches or retries a method.
        """
        return self.station_service.execute(self.raw_credential, {
            'action': 'native-logs', 'request_id': request_id, 'offset': offset, 'limit': limit, 'stream': stream})

    def run_logs(self, run_id: str, attempt_id: str, offset: int = 0, limit: int = 65536,
                 stream: Literal['receipt', 'trace'] = 'receipt') -> dict[str, Any]:
        """Read an experiment attempt's captured receipt or trace without starting or retrying it.

        Obtain attempt_id from run_status execution evidence. Content is base64 with byte cursors.
        Receipt JSON is UTF-8; vendor trace encoding is driver-defined. Output may be pending.
        Completion and commanded centrifuge settings are not measured RPM or delivered volume.
        """
        return self.station_service.execute(self.raw_credential, {
            'action': 'run-logs', 'run_id': run_id, 'attempt_id': attempt_id,
            'offset': offset, 'limit': limit, 'stream': stream})

    def initialize_station(self, request_id: str, method_id: str, bundle_sha256: str,
                           acknowledge_clearance: bool) -> dict[str, Any]:
        """Initialize hardware using the exact driver method returned by describe_station_service.

        Requires explicit operator clearance and an idle station. This can move hardware.
        Preserve request_id; after a timeout query station_service_status, never submit a new ID.
        An accepted response is not completion. Does not start an experiment.
        """
        return self.station_service.execute(self.raw_credential, {
            'action': 'initialize', 'request_id': request_id, 'method_id': method_id,
            'bundle_sha256': bundle_sha256, 'acknowledge_clearance': acknowledge_clearance})

    def station_service_status(self, request_id: str) -> dict[str, Any]:
        """Reconcile the original initialization or native maintenance request without redispatching it."""
        return self.station_service.execute(self.raw_credential, {
            'action': 'status', 'request_id': request_id})

    def cancel_station_service(self, request_id: str) -> dict[str, Any]:
        """Cancel initialization or native maintenance and release its reservation, retaining history.

        The driver must establish that execution is idle before releasing a started job.
        This is not an emergency hardware stop. Query the same request after a lost response.
        """
        return self.station_service.execute(self.raw_credential, {
            'action': 'cancel', 'request_id': request_id})

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

    def confirm_loading(self, run_id: str, fingerprint: str, request_id: str,
                        acknowledged: bool) -> dict[str, Any]:
        """Confirm the exact loading plan and submit for execution, which can move hardware.

        acknowledged must be true only after the operator has confirmed the displayed
        requirements and authorized execution. Existing explicit authorization may be
        used; another console click is not required. This is an attestation, not a
        sensor observation. Call begin_loading first. Retain request_id and poll
        loading_request_status after any timeout; acceptance is not completion.
        """
        return self.setup_confirmation.execute(self.raw_credential, SetupInteractionRequest(
            'confirm', run_id, request_id, fingerprint, acknowledged=acknowledged))

    def list_programs(self) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('list'))

    def inspect_program(self, program_id: str, source_scope: str = 'programs') -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('inspect', program_id, source_scope=source_scope))

    def preview_program(self, program_id: str, source_scope: str = 'programs') -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('preview', program_id,
            source_scope=source_scope))

    def submit_program(self, program_id: str, snapshot_id: str, request_id: str,
                       configuration_fingerprint: str | None = None, source_scope: str = 'programs') -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('submit', program_id, snapshot_id,
            request_id, configuration_fingerprint=configuration_fingerprint,source_scope=source_scope))

    def prepare_program(self, program_id: str, snapshot_id: str, request_id: str,
                        configuration_fingerprint: str | None = None, source_scope: str = 'programs',
                        workflow_revision: int | None = None) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('prepare', program_id, snapshot_id,
            request_id, configuration_fingerprint=configuration_fingerprint, source_scope=source_scope,
            workflow_revision=workflow_revision))

    def start_program(self, program_id: str, snapshot_id: str, request_id: str,
                      configuration_fingerprint: str | None = None, source_scope: str = 'programs') -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('start', program_id, snapshot_id,
            request_id, configuration_fingerprint=configuration_fingerprint,source_scope=source_scope))

    def control_run(self, run_id: str, action: Literal['pause','resume','cancel'], request_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest(action, request_id=request_id, run_id=run_id))

    def control_request_status(self, run_id: str, request_id: str) -> dict[str, Any]:
        return self.programs.execute(self.raw_credential, ConsoleProgramRequest('control-status', request_id=request_id, run_id=run_id))

    def view_state(self) -> dict[str, Any]:
        return self.view_reads.execute(self.raw_credential, ViewStateReadRequest())

    def view_request_status(self, request_id: str) -> dict[str, Any]:
        return self.view_reads.execute(self.raw_credential, ViewStateReadRequest('receipt', request_id))

    def open_view(self, session_id: str, epoch: str, expected_revision: int, request_id: str,
                  view: Literal['desktop','experiment','workstation','files','settings','system_info','developer','editor'],
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

    def file_roots(self) -> dict[str,Any]:
        """Read the server-selected user workspace and experiment directory roots."""
        return self.file_reads.execute(self.raw_credential,FileReadRequest('roots'))

    def list_directory(self,root:str='installation',path:str='',offset:int=0) -> dict[str,Any]:
        """Read a directory page. Paths are relative to the selected user workspace root."""
        return self.file_reads.execute(self.raw_credential,FileReadRequest('list',root,path,offset))

    def preview_file(self,root:str,path:str) -> dict[str,Any]:
        """Read a bounded text preview or binary-file metadata; never execute the file."""
        return self.file_reads.execute(self.raw_credential,FileReadRequest('preview',root,path))


    def read_document(self,path:str) -> dict[str,Any]:
        """Read editable experiment source with its current revision; no run is started."""
        from culsma_os.file_system.models import FileWorkspaceRequest
        return self.file_workspace.execute(self.raw_credential,FileWorkspaceRequest('read',path))

    def create_document(self,path:str,content:str) -> dict[str,Any]:
        """Create a .culs file in Experiments; existing files are never overwritten."""
        from culsma_os.file_system.models import FileWorkspaceRequest
        return self.file_workspace.execute(self.raw_credential,FileWorkspaceRequest('create',path,content))

    def save_document(self,path:str,content:str,expected_revision:str) -> dict[str,Any]:
        """Save .culs source only against the revision read earlier; conflicts preserve both edits."""
        from culsma_os.file_system.models import FileWorkspaceRequest
        return self.file_workspace.execute(self.raw_credential,FileWorkspaceRequest('save',path,content,expected_revision))

    def receive_files(self,entries:list[dict[str,str]],directory:str='') -> dict[str,Any]:
        """Copy a bounded package into Experiments. Entries contain relative path and base64 data; never execute or overwrite files."""
        from culsma_os.file_system.models import FileWorkspaceRequest
        return self.file_workspace.execute(self.raw_credential,FileWorkspaceRequest('receive',directory,entries=entries))
