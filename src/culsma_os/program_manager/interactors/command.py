"""Own complete Culsma compilation and execution outside transport adapters."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json
from culsma.runtime.executor import run
from culsma.runtime.inventory import reconcile_external_inventory
from culsma.runtime.results import build_results
from culsma.runtime.user_result import build_unexecuted_report
from culsma_os.driver_framework.models import DriverBuildContext, DriverLoadError
from ..models import CommandRequest, HostBuildContext


class ProgramRunInteractor:

    def __init__(self, applications, drivers, compilation, ownership=None):
        self.applications = applications
        self.drivers = drivers
        self.ownership = ownership
        self.compilation = compilation

    def protocol_returns_from_state(self, state: Any) -> dict[str, Any]:
        artifacts = getattr(state, "artifacts", {})
        if not isinstance(artifacts, dict):
            return {}
        outputs = artifacts.get("protocol_outputs")
        if not isinstance(outputs, dict):
            return {}
        return {
            str(name): payload
            for name, payload in outputs.items()
            if isinstance(payload, dict)
        }

    def build_run_output(
        self, *, ok: bool, returns: dict[str, Any], report: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "schema": "culsma_run_output_v1",
            "ok": ok,
            "returns": returns,
            "report": report,
        }

    def build_batch_run_output(
        self, *, run_items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        runs = []
        for item in run_items:
            bundle = item["bundle"]
            runs.append(
                {
                    "input": str(item["input"]),
                    "ok": bool(bundle["output"].get("ok")),
                    "output": bundle["output"],
                    "summary": bundle["summary"],
                }
            )
        return {
            "schema": "culsma_batch_run_output_v1",
            "ok": all((run["ok"] for run in runs)),
            "runs": runs,
        }

    def load_initial_material_state(
        self, material_state_path: Path | None
    ) -> dict[str, Any]:
        return self.compilation.load_material_state(material_state_path)

    def load_inventory_snapshot(
        self, inventory_path: Path | None
    ) -> dict[str, Any] | None:
        if inventory_path is None:
            return None
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(
                "INVENTORY_SNAPSHOT_INVALID: snapshot root must be an object"
            )
        return payload

    def execute_pipeline(
        self,
        input_paths: list[Path],
        fail_ops: set[str] | None = None,
        material_state_path: Path | None = None,
        inventory_check: bool | dict[str, Any] | None = None,
        library_roots: list[Path] | None = None,
        driver_name: str = "stub",
        driver_config_path: Path | None = None,
        driver_artifacts_dir: Path | None = None,
        execution_mode: str = "os",
        host_database_path: Path | None = None,
        station_id: str | None = None,
        workspace_config_path: Path | None = None,
    ) -> dict[str, Any]:
        if execution_mode not in {"os", "driver"}:
            raise ValueError("EXECUTION_MODE_UNSUPPORTED")
        if workspace_config_path is not None and execution_mode != 'os':
            raise ValueError('WORKSPACE_CONFIG_REQUIRES_OS')
        if len(input_paths) != 1:
            raise ValueError(
                "RUN_SINGLE_ENTRY_SOURCE_REQUIRED: execute_pipeline requires exactly one entry source"
            )
        compiled = self.compilation.compile(input_paths, material_state_path, library_roots or ())
        frontend, ir = compiled.frontend, compiled.ir
        sem, typ, plan, state = compiled.semantic, compiled.typed, compiled.plan, compiled.state
        initial_material_state = compiled.initial_material_state
        can_run = sem.ok and typ.ok and not any(d.severity == "error" for d in plan.diagnostics)
        if can_run:
            context = DriverBuildContext(
                plan=plan,
                state=state,
                config_path=driver_config_path,
                artifacts_dir=driver_artifacts_dir or Path("run-artifacts/drivers"),
                fail_ops=frozenset(fail_ops or ()),
            )
            if execution_mode == "driver":
                with self.drivers.open_session(driver_name, context) as driver:
                    run_result = run(plan=plan, driver=driver, state=state)
            else:
                if fail_ops:
                    raise DriverLoadError("HOST_FAIL_OP_UNSUPPORTED")
                host_context = HostBuildContext(
                    host_database_path or Path("run-artifacts/culsma-os.sqlite3"),
                    driver_name, driver_config_path, context.artifacts_dir, station_id,
                    workspace_config_path=workspace_config_path)
                run_result = self.execute_one_shot(host_context, plan, state)
            if run_result.user_result is None:
                raise RuntimeError(
                    "RUN_REPORT_MISSING: Runtime execution completed without a report"
                )
            user_result = run_result.user_result
        else:
            run_result = SimpleNamespace(
                ok=False,
                diagnostics=list(plan.diagnostics),
                state=state,
                events=[],
                material_accounting=None,
            )
            user_result = build_unexecuted_report(
                ok=run_result.ok,
                diagnostics=list(run_result.diagnostics),
                state=run_result.state,
                plan=plan,
                initial_material_state=initial_material_state,
            )
        user_result = reconcile_external_inventory(
            report=user_result,
            snapshot=inventory_check if isinstance(inventory_check, dict) else None,
        )
        run_payload = {
            "ok": run_result.ok,
            "diagnostics": [d.to_dict() for d in run_result.diagnostics],
            "state": run_result.state.to_dict(),
            "events": [e.to_dict() for e in run_result.events],
            "user_result": user_result,
        }
        returns = self.protocol_returns_from_state(run_result.state)
        output = self.build_run_output(
            ok=run_result.ok, returns=returns, report=user_result
        )
        summary = {
            "inputs": [str(p) for p in input_paths],
            "semantic_error_count": sum(
                (1 for d in sem.diagnostics if d.severity == "error")
            ),
            "type_error_count": sum(
                (1 for d in typ.diagnostics if d.severity == "error")
            ),
            "plan_diagnostic_count": len(plan.diagnostics),
            "runtime_diagnostic_count": len(run_result.diagnostics),
            "runtime_ok": run_result.ok,
            "total_steps": len(run_result.state.step_status),
            "completed_steps": sum(
                (1 for s in run_result.state.step_status.values() if s == "completed")
            ),
            "failed_steps": sum(
                (1 for s in run_result.state.step_status.values() if s == "failed")
            ),
            "skipped_steps": sum(
                (1 for s in run_result.state.step_status.values() if s == "skipped")
            ),
            "user_result_available": True,
        }
        return {
            "ast": frontend.parsed_program,
            "ir": ir.to_dict(),
            "validate": [d.to_dict() for d in sem.diagnostics],
            "typecheck": [d.to_dict() for d in typ.diagnostics],
            "plan": plan.to_dict(),
            "run": run_payload,
            "returns": returns,
            "output": output,
            "results": build_results(
                state=run_result.state,
                returns=returns,
                plan=plan,
                material_accounting=run_result.material_accounting,
            ),
            "result": user_result,
            "summary": summary,
        }

    def execute_one_shot(self, context: HostBuildContext, plan, state):
        """Own a temporary host for this call, without discovering a resident host."""
        from contextlib import nullcontext
        with self.ownership.embedded(context) if self.ownership else nullcontext():
            host = self.applications.build(context)
            try:
                return host.execute(plan, state)
            finally:
                host.close()

    def execute_batch_pipeline(
        self,
        input_paths: list[Path],
        fail_ops: set[str] | None = None,
        material_state_path: Path | None = None,
        inventory_check: bool | dict[str, Any] | None = None,
        library_roots: list[Path] | None = None,
        driver_name: str = "stub",
        driver_config_path: Path | None = None,
        driver_artifacts_dir: Path | None = None,
        execution_mode: str = "os",
        host_database_path: Path | None = None,
        station_id: str | None = None,
        workspace_config_path: Path | None = None,
    ) -> dict[str, Any]:
        if not input_paths:
            raise ValueError(
                "RUN_NO_INPUT_SOURCES: No input source files were provided"
            )
        if len(input_paths) == 1:
            return self.execute_pipeline(
                input_paths=input_paths,
                fail_ops=fail_ops,
                material_state_path=material_state_path,
                inventory_check=inventory_check,
                library_roots=library_roots,
                driver_name=driver_name,
                driver_config_path=driver_config_path,
                driver_artifacts_dir=driver_artifacts_dir,
                execution_mode=execution_mode,
                host_database_path=host_database_path,
                station_id=station_id,
                workspace_config_path=workspace_config_path,
            )
        run_items = []
        for input_path in input_paths:
            run_items.append(
                {
                    "input": input_path,
                    "bundle": self.execute_pipeline(
                        input_paths=[input_path],
                        fail_ops=fail_ops,
                        material_state_path=material_state_path,
                        inventory_check=inventory_check,
                        library_roots=library_roots,
                        driver_name=driver_name,
                        driver_config_path=driver_config_path,
                        driver_artifacts_dir=driver_artifacts_dir,
                        execution_mode=execution_mode,
                        host_database_path=host_database_path,
                        station_id=station_id,
                        workspace_config_path=workspace_config_path,
                    ),
                }
            )
        output = self.build_batch_run_output(run_items=run_items)
        return {
            "batch": True,
            "runs": run_items,
            "output": output,
            "results": [item["bundle"]["results"] for item in run_items],
            "summary": {
                "inputs": [str(path) for path in input_paths],
                "run_count": len(run_items),
                "ok_count": sum((1 for run_item in output["runs"] if run_item["ok"])),
                "runtime_ok": output["ok"],
            },
        }

    def execute(self, request):
        snapshot = (
            self.load_inventory_snapshot(request.inventory_path)
            if request.inventory_path is not None
            else request.inventory_check
        )
        return self.execute_batch_pipeline(
            input_paths=request.input_paths,
            fail_ops=request.fail_ops,
            material_state_path=request.material_state_path,
            inventory_check=snapshot,
            library_roots=request.library_roots,
            driver_name=request.driver_name,
            driver_config_path=request.driver_config_path,
            driver_artifacts_dir=request.driver_artifacts_dir,
            execution_mode=request.execution_mode,
            host_database_path=request.host_database_path,
            station_id=request.station_id,
            workspace_config_path=request.workspace_config_path,
        )
