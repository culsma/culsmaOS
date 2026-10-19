"""OS command adapter, separately owned from the language CLI."""

import argparse
import json
from pathlib import Path
from culsma.cli import (
    format_terminal_result,
    format_batch_terminal_result,
    write_run_artifacts,
)
from culsma_os.program_manager.models import CommandRequest, RunControlRequest, HostBuildContext
from culsma_os.driver_framework.models import DriverLoadError
from culsma_os.bootstrap import OSApplicationFactory


class CulsmaOSCLI:
    @staticmethod
    def main(argv=None):
        parser = argparse.ArgumentParser(prog="culsma-os")
        commands = parser.add_subparsers(dest="command", required=True)
        for command in ("run", "driver-run"):
            run = commands.add_parser(
                command,
                help=(
                    "Run once and exit"
                    if command == "run"
                    else "Direct driver diagnostic execution"
                ),
            )
            run.add_argument("inputs", nargs="+", type=Path)
            run.add_argument(
                "--driver",
                default="opentrons-simulator" if command == "run" else "stub",
            )
            run.add_argument("--driver-config", type=Path)
            run.add_argument("--workspace-config", type=Path)
            run.add_argument("--host-db", type=Path)
            run.add_argument("--station-id")
            run.add_argument(
                "--artifacts-dir", type=Path, default=Path("run-artifacts")
            )
            run.add_argument("--material-state", type=Path)
            run.add_argument("--inventory-check", type=Path)
            run.add_argument("--library-root", action="append", type=Path, default=[])
            run.add_argument("--fail-op", action="append", default=[])
        for action in ("resume", "pause", "cancel", "status"):
            control = commands.add_parser(action, help=f"{action.title()} a saved OS run")
            control.add_argument("run_id")
            target = control.add_mutually_exclusive_group(required=True)
            target.add_argument("--host-db", type=Path)
            target.add_argument("--socket", type=Path)
            control.add_argument("--driver", default="opentrons-simulator")
            control.add_argument("--driver-config", type=Path)
            control.add_argument("--workspace-config", type=Path)
            control.add_argument("--artifacts-dir", type=Path, default=Path("run-artifacts"))
            control.add_argument("--station-id")
        serve = commands.add_parser("serve", help="Start the persistent local OS host")
        serve.add_argument("--socket", type=Path, required=True)
        serve.add_argument("--host-db", type=Path, required=True)
        serve.add_argument("--driver", default="opentrons-simulator")
        serve.add_argument("--driver-config", type=Path)
        serve.add_argument("--workspace-config", type=Path)
        serve.add_argument("--station-id")
        serve.add_argument("--artifacts-dir", type=Path, default=Path("run-artifacts"))
        submit = commands.add_parser("submit", help="Submit to an existing host and return a run ID")
        submit.add_argument("source", type=Path)
        submit.add_argument("--socket", type=Path, required=True)
        submit.add_argument("--material-state", type=Path)
        submit.add_argument("--library-root", action="append", type=Path, default=[])
        submit.add_argument("--request-id")
        for action in ("runs", "host-status", "host-stop", "device-status"):
            remote = commands.add_parser(action)
            remote.add_argument("--socket", type=Path, required=True)
        console = commands.add_parser("console", help="Operate resident programs and edit offline configuration drafts")
        console.add_argument("--socket", type=Path, required=True)
        console.add_argument("--port", type=int, default=8765)
        console.add_argument("--drafts-db", type=Path, default=Path("run-artifacts/console/drafts.sqlite3"))
        console.add_argument("--program-root", type=Path, help="Allow console selection of .culs files under this directory")
        console.add_argument("--program-store", type=Path, default=Path("run-artifacts/console/programs"))
        args = parser.parse_args(argv)
        if args.command == "console":
            from culsma_os.console.models import ConsoleSettings
            from culsma_os.console.providers import ConsoleApplicationFactory
            try:
                server = ConsoleApplicationFactory().build(ConsoleSettings(args.socket.resolve(), args.port, args.drafts_db.resolve(), args.program_root, args.program_store.resolve()))
            except (ValueError, OSError) as error:
                parser.exit(2, f"{error}\n")
            try:
                print(f"Station console: {server.url}", flush=True)
                print("Draft editing is offline; explicit application is handled by the resident service.", flush=True)
                server.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            raise SystemExit(0)
        if args.command == "serve":
            from culsma_os.lifecycle_manager.models import ResidentHostSettings
            import signal
            context = HostBuildContext(args.host_db.resolve(), args.driver,
                args.driver_config.resolve() if args.driver_config else None,
                args.artifacts_dir.resolve() / "driver", args.station_id,
                workspace_config_path=args.workspace_config.resolve() if args.workspace_config else None)
            host = OSApplicationFactory().build_resident_host(ResidentHostSettings(context, args.socket.resolve()))
            previous = signal.signal(signal.SIGTERM, host.request_stop)
            try:
                host.serve()
            except (DriverLoadError, ValueError, OSError) as error:
                parser.exit(2, f"{error}\n")
            finally:
                signal.signal(signal.SIGTERM, previous)
            raise SystemExit(0)
        if args.command in {"submit", "runs", "host-status", "host-stop", "device-status"} or getattr(args, "socket", None):
            from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
            payload = {"action": "shutdown" if args.command == "host-stop" else args.command}
            if args.command == "submit":
                payload.update(source=str(args.source.resolve()),
                    material_state=str(args.material_state.resolve()) if args.material_state else None,
                    library_roots=[str(p.resolve()) for p in args.library_root])
                if args.request_id:
                    payload["request_id"] = args.request_id
            elif hasattr(args, "run_id"):
                payload["run_id"] = args.run_id
            try:
                result = ResidentClientAdapter(args.socket).execute(payload)
            except (ValueError, OSError) as error:
                parser.exit(2, f"{error}\n")
            print(json.dumps(result, ensure_ascii=False, default=str))
            raise SystemExit(0)

        if args.command in {"resume", "pause", "cancel", "status"}:
            if args.host_db is None:
                parser.error("provide --socket for a resident host or --host-db for an embedded run")
            request = RunControlRequest(args.command, args.run_id,
                HostBuildContext(args.host_db, args.driver, args.driver_config,
                                 args.artifacts_dir / "driver", args.station_id,
                                 workspace_config_path=args.workspace_config))
            try:
                result = OSApplicationFactory().build_run_controller().execute(request)
            except (DriverLoadError, ValueError, OSError, KeyError) as error:
                parser.exit(2, f"{error}\n")
            print(json.dumps(result, ensure_ascii=False, default=str))
            raise SystemExit(0 if args.command != "resume" or result["ok"] else 1)
        request = CommandRequest(
            input_paths=args.inputs,
            fail_ops=set(args.fail_op),
            material_state_path=args.material_state,
            inventory_path=args.inventory_check,
            library_roots=args.library_root,
            driver_name=args.driver,
            driver_config_path=args.driver_config,
            driver_artifacts_dir=args.artifacts_dir / "driver",
            execution_mode="os" if args.command == "run" else "driver",
            host_database_path=args.host_db or args.artifacts_dir / "culsma-os.sqlite3",
            station_id=args.station_id,
            workspace_config_path=args.workspace_config,
        )
        try:
            result = OSApplicationFactory().build_program_runner().execute(request)
        except (DriverLoadError, ValueError, OSError) as error:
            parser.exit(2, f"{error}\n")
        write_run_artifacts(result, args.artifacts_dir)
        print(
            format_batch_terminal_result(result)
            if result.get("batch")
            else format_terminal_result(result)
        )
        raise SystemExit(0 if result["output"]["ok"] else 1)


if __name__ == "__main__":
    CulsmaOSCLI.main()
