from tests.support.paths import ROOT
from pathlib import Path
import importlib.metadata
import json
import subprocess
import sys
import pytest
from culsma import cli
from culsma_os.bootstrap import OSApplicationFactory, LanguageProgramExecutorFactory
from culsma.driver.models import ProgramExecutionRequest
from tests.support.integration.language_cli import ROOT, SOURCE, DECK


class TestLanguageCLI:
    def test_separate_console_ownership(self):
        project = (ROOT / "pyproject.toml").read_text()
        assert 'culsma-os = "culsma_os.cli:CulsmaOSCLI.main"' in project
        assert "culsma-cli =" not in project and "\nculsma =" not in project
        assert not (ROOT / "bin/culsma").exists()
        assert not (ROOT / "tools/activate-cli.sh").exists()
        assert not (ROOT / "src/culsma_os/compat_cli.py").exists()

    def test_provider_admits_complete_program(self, monkeypatch, tmp_path):
        calls = []

        class Runner:
            def execute(self, request):
                calls.append(request)
                return {"output": {"ok": True}}

        monkeypatch.setattr(
            OSApplicationFactory, "build_program_runner", lambda self: Runner()
        )
        request = ProgramExecutionRequest(
            (SOURCE,), "opentrons-simulator", DECK, tmp_path
        )
        LanguageProgramExecutorFactory().build().execute(request)
        assert calls[0].input_paths == [SOURCE] and calls[0].execution_mode == "os"
        assert (
            calls[0].driver_config_path == DECK
            and calls[0].host_database_path == tmp_path / "culsma-os.sqlite3"
        )

    def test_original_console_runs_os(self, tmp_path):
        pytest.importorskip("culsma_opentrons")
        console = Path(sys.executable).parent / "culsma"
        assert "from culsma.cli import main" in console.read_text()
        artifacts = tmp_path / "artifacts"
        result = subprocess.run(
            [
                str(console),
                "run",
                str(SOURCE),
                "--driver",
                "opentrons-simulator",
                "--driver-config",
                str(DECK),
                "--artifacts-dir",
                str(artifacts),
                "--json",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["report"]["os"]["status"] == "completed"
        run = json.loads((artifacts / "run.json").read_text())
        assert sorted(
            c["volume_uL"]
            for c in run["state"]["artifacts"]["material_state"]["containers"].values()
        ) == [100, 100]
        import sqlite3

        with sqlite3.connect(artifacts / "culsma-os.sqlite3") as connection:
            assert (
                connection.execute("SELECT count(*) FROM os_attempts").fetchone()[0]
                == 2
            )
            assert (
                connection.execute("SELECT count(*) FROM os_evidence").fetchone()[0]
                == 2
            )

    def test_plain_language_cli_still_runs_without_os(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "culsma.cli", "run", str(SOURCE), "--json"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "os" not in json.loads(result.stdout)["report"]
        assert not (tmp_path / "run-artifacts").exists()

    def test_language_compile_error_never_starts_device(self, monkeypatch, tmp_path):
        source = tmp_path / "bad.culs"
        source.write_text("let dst = tube(); dst << [missing:50uL];")

        def forbidden(*args):
            raise AssertionError("Device created before language validation")

        monkeypatch.setattr(OSApplicationFactory, "build", forbidden)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "culsma",
                "run",
                str(source),
                "--driver",
                "opentrons-simulator",
                "--driver-config",
                str(DECK),
                "--json",
            ],
        )
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1

