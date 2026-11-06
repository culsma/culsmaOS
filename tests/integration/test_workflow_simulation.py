"""A real HTTP console and resident drive the same local simulation policy."""
from dataclasses import replace
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from uuid import uuid4

import pytest

from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.console.models import ConsoleSettings
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from tests.support.console.http import ConsoleHTTPHarness
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture


def wait_for(predicate):
    deadline = monotonic() + 15
    while monotonic() < deadline:
        try:
            result = predicate()
        except OSError:
            result = None
        if result:
            return result
        sleep(0.02)
    pytest.fail("Resident did not reach the expected state")


def test_settings_control_real_console_start_and_record_synthetic_readout(tmp_path):
    fixture = TransferMatrixFixture()
    source = fixture.source("""
        target << [source:30uL];
        let readout = img(sample=target, quantity=fluorescence);
        target << [source:25uL];
    """)
    context = replace(fixture.context(tmp_path, fixture.compile(source, tmp_path)),
                      station_root=tmp_path / "station")
    programs = tmp_path / "experiments"
    programs.mkdir()
    (programs / "readout.culs").write_text(source)
    (programs / "raw.culs").write_text(source.replace("quantity=fluorescence", "quantity=fluorescence, save_raw=true"))
    socket = Path("/private/tmp") / f"culsma-workflow-{uuid4().hex[:12]}.sock"
    factory = OSApplicationFactory()
    settings = ResidentHostSettings(context, socket, 0.01)
    resident = ResidentClientAdapter(socket)
    failures = []

    def serve():
        try:
            factory.build_resident_host(settings).serve()
        except Exception as error:
            failures.append(error)

    def start_host():
        thread = Thread(target=serve, daemon=True)
        thread.start()
        wait_for(lambda: resident.execute({"action": "host-status"})["status"] == "ready")
        return thread

    def stop_host(thread):
        resident.execute({"action": "shutdown"})
        thread.join(10)
        assert not thread.is_alive() and not failures

    thread = start_host()
    server = ConsoleApplicationFactory().build(ConsoleSettings(socket, 0, tmp_path / "drafts.sqlite3",
        programs, tmp_path / "snapshots", serve_frontend=False))
    credential = server.sessions.execute()["access_token"]
    headers = {"Origin": server.url, "Content-Type": "application/json", "Authorization": f"Bearer {credential}"}
    endpoint = "/api/v1/configuration/workflow-simulation"

    try:
        with ConsoleHTTPHarness(server) as console:
            def preview(name):
                code, _, body = console.request("POST", "/api/v1/programs", headers,
                    {"action": "preview", "program_id": name})
                assert code == 200, body
                return body["data"]

            disabled = preview("readout.culs")
            assert not disabled["valid"]
            assert disabled["diagnostics"][0]["code"] == "HOST_OPERATION_UNSUPPORTED"
            assert resident.execute({"action": "runs"})["runs"] == []
            assert console.request("POST", endpoint, {**headers, "Authorization": ""}, {"enabled": True, "revision": 0})[0] == 401
            assert console.request("POST", endpoint, headers, {"enabled": True, "revision": 0})[0] == 200
            assert console.request("POST", endpoint, headers, {"enabled": False, "revision": 0})[0] == 409
            assert not preview("raw.culs")["valid"]
            reviewed = preview("readout.culs")
            assert reviewed["valid"], reviewed["diagnostics"]
            workflow = reviewed["preparation"]["workflow_simulation"]
            route, = workflow["routes"].values()
            assert route["provider"] == "internal_fluorescence_fixture_v1"
            payload = {"action": "start", "program_id": "readout.culs", "snapshot_id": reviewed["snapshot_id"],
                       "request_id": "workflow-example", "workflow_revision": workflow["revision"]}
            assert console.request("POST", endpoint, headers, {"enabled": False, "revision": 1})[0] == 200
            code, _, body = console.request("POST", "/api/v1/programs", headers, payload)
            assert code == 409 and body["error"]["code"] == "WORKFLOW_SIMULATION_SETTING_STALE"
            assert console.request("POST", endpoint, headers, {"enabled": True, "revision": 2})[0] == 200
            payload["workflow_revision"] = 3
            code, _, body = console.request("POST", "/api/v1/programs", headers, payload)
            assert code == 200, body
            run_id = body["data"]["run"]["run_id"]
            assert console.request("POST", endpoint, headers, {"enabled": False, "revision": 3})[0] == 200
            record = wait_for(lambda: (row if (row := resident.execute({"action": "status", "run_id": run_id}))
                                      ["status"] in {"completed", "failed", "rejected"} else None))
            assert record["status"] == "completed", record
            report = record["result"]["os"]
            assert report["workflow_simulation"]["steps"] == [{**route, "status": "completed"}]
            containers = report["registered_material"]["state"]["containers"]
            assert sorted(row["volume_uL"] for row in containers.values()) == [55, 145]
            detail = console.request("GET", f"/api/v1/runs/{run_id}")[2]["data"]
            assert len(detail["execution_evidence"]["attempts"]) == 2
            code, _, body = console.request("POST", "/api/v1/programs", headers, payload)
            assert code == 200 and body["data"]["run"]["run_id"] == run_id
        inspector = factory.build_run_inspector(context)
        try:
            checkpoint = inspector.tasks.get(run_id).checkpoint
            with pytest.raises(ValueError, match="RUN_SIMULATION_MODE_REQUIRED"):
                HostedRuntimeInteractor(execution_mode="physical").advance(checkpoint)
        finally:
            inspector.close()
    finally:
        stop_host(thread)

    thread = start_host()
    try:
        status = resident.execute({"action": "host-status"})
        assert status["workflow_simulation"] == {"enabled": False, "revision": 4}
        from culsma_os.program_manager.models import ConsoleProgramError
        from culsma_os.auth.models import ConsoleAccessError
        bridge = ConsoleApplicationFactory().build_mcp(server.settings)
        tools = bridge.server
        tools.raw_credential = 'Bearer ' + bridge.tokens.issue_automation_session()
        assert (tools.set_workflow_simulation, False) in tools.settings_tools()
        tools.set_workflow_simulation(True, 4)
        assert resident.execute({"action": "host-status"})["workflow_simulation"] == {"enabled": True, "revision": 5}
        with pytest.raises(ConsoleProgramError):
            tools.set_workflow_simulation(False, 4)
        tools.set_workflow_simulation(False, 5)
        assert resident.execute({"action": "host-status"})["workflow_simulation"] == {"enabled": False, "revision": 6}
        tools.raw_credential = ''
        with pytest.raises(ConsoleAccessError):
            tools.set_workflow_simulation(True, 6)
        assert resident.execute({"action": "status", "run_id": run_id})["result"]["os"]["workflow_simulation"] == report["workflow_simulation"]
    finally:
        stop_host(thread)
