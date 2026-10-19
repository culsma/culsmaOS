from tests.support.paths import ROOT
from pathlib import Path
import ast
import json
from tests.support.architecture.architecture import ROOT, SRC


class TestArchitecture:
    def test_architecture_boundaries(self):
        allowed = {
            "program_manager",
            "scheduler",
            "material_system",
            "workspace_manager",
            "transfer_engine",
            "processing_engine",
            "resource_manager",
            "device_manager",
            "driver_framework",
            "event_journal",
            "recovery_manager",
            "lifecycle_manager",
            "auth",  # Process-local credential owner for writable console use cases.
            "console",  # Transport/composition package, not a second execution subsystem.
        }
        assert {
            p.name for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__"
        } == allowed
        for path in SRC.rglob("*.py"):
            tree = ast.parse(path.read_text())
            relative = path.relative_to(SRC)
            assert not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                for node in tree.body
            ), path
            if len(relative.parts) > 1:
                assert relative.parts[1] in {
                    "__init__.py",
                    "models.py",
                    "interactors.py",
                    "interactors",
                    "repository.py",
                    "repositories",
                    "adapters",
                    "providers.py",
                }, path
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                names = {a.name for a in node.names}
                if path.name == "api.py" or "adapters" in relative.parts:
                    assert not any("Repository" in n for n in names), path
                if "interactors" in relative.parts or path.name == "interactors.py":
                    assert not any(
                        n.startswith(("Sqlite", "Local")) and n.endswith("Repository")
                        for n in names
                    ), path
                if relative.parts[0] == "event_journal":
                    assert not (node.module or "").startswith(
                        "culsma_os.program_manager"
                    ), path
        assert (
            "ResourceInteractor"
            not in (SRC / "driver_framework/interactors.py").read_text()
        )
        assert (
            "simulated"
            not in (SRC / "event_journal/interactors/evidence.py").read_text()
        )

    def test_component_paths_and_classes_match_source(self):
        index = json.loads((ROOT / "tests/architecture/module-map.json").read_text())
        assert index["schema"] == "culsma_source_components_v1"
        for module in index["modules"]:
            assert (ROOT / module["directory"]).is_dir(), module["module"]
            for component in module["components"]:
                path = ROOT / component["path"]
                assert path.is_file(), component
                classes = {node.name for node in ast.walk(ast.parse(path.read_text()))
                           if isinstance(node, ast.ClassDef)}
                assert component["component"] in classes, component

    def test_vendor_boundary_is_thin(self):
        plugin_source = (SRC / "bootstrap.py").read_text()
        assert "OfficialSimulatorBackend" not in plugin_source
        assert "DeckConfiguration" not in plugin_source
        assert "OT_API_CONFIG_DIR" not in plugin_source
        adapter = (SRC / "driver_framework/adapters/opentrons.py").read_text()
        assert ".backend" not in adapter and ".pipette" not in adapter
        assert ".translator" not in adapter
        for file in [
            "driver_framework/interactors.py",
            "resource_manager/interactors.py",
        ]:
            text = (SRC / file).read_text()
            assert "stroke_id" not in text and "pick_up_tip" not in text
            assert 'description["transfers"]' not in text
        for path in SRC.rglob("*.py"):
            if "adapters" not in path.parts and path.name != "bootstrap.py":
                assert "culsma_opentrons" not in path.read_text(), path

    def test_external_cli_has_only_adapter_responsibilities(self):
        tree = ast.parse((SRC / "cli.py").read_text())
        imports = [
            n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        ]
        assert not any(
            name.startswith(
                ("culsma.pipeline", "culsma.runtime.executor", "culsma.frontend")
            )
            for name in imports
        )
        assert not any(
            "Repository" in a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
            for a in n.names
        )
        assert "ProgramRunInteractor" in (SRC / "bootstrap.py").read_text()

    def test_semantic_adapter_uses_public_language_boundary(self):
        for name in [
            "program_manager/interactors/semantics.py",
            "program_manager/interactors/replay.py",
        ]:
            tree = ast.parse((SRC / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith(
                        (
                            "culsma.runtime.hosts",
                            "culsma.runtime.steps",
                            "culsma.driver.loading",
                        )
                    )
                    assert not any(a.name.startswith("_") for a in node.names)
                if isinstance(node, ast.Attribute):
                    assert not node.attr.startswith("_"), (name, node.attr)
        adapter = (SRC / "driver_framework/adapters/semantic.py").read_text()
        assert "MaterialCompute" not in adapter and "entry_points" not in adapter

    def test_language_core_has_only_generic_execution_contracts(self):
        import ast
        import culsma
        from culsma.runtime.executor import RuntimeExecutor, RunResult

        root = Path(culsma.__file__).resolve().parent
        assert not (root / "execution.py").exists()
        assert not (root / "driver/loading.py").exists()
        assert not (root / "runtime/hosts").exists()
        assert not hasattr(RuntimeExecutor, "create_session")
        assert "settled" not in RunResult.__dataclass_fields__
        for file in root.rglob("*.py"):
            tree = ast.parse(file.read_text())
            imports = [
                n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            ]
            imports += [
                a.name
                for n in ast.walk(tree)
                if isinstance(n, ast.Import)
                for a in n.names
            ]
            assert not any(
                name.startswith(
                    ("culsma_os", "culsma_opentrons", "culsma_driver_hamilton")
                )
                for name in imports
            ), file
        cli = (root / "cli.py").read_text()
        assert '"--host"' not in cli
        assert '"--driver"' in cli and '"--driver-config"' in cli
        assert "ProgramExecutionInteractor" in cli

    def test_control_plane_does_not_construct_device_sessions(self):
        source = (SRC / "program_manager/interactors/control.py").read_text()
        tree = ast.parse(source)
        inspector = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RunInspectionInteractor")
        calls = {n.func.attr for n in ast.walk(inspector) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert not calls & {"build", "register", "prepare", "restore_consumables", "take_over_run"}
        factory = ast.parse((SRC / "bootstrap.py").read_text())
        builder = next(n for n in ast.walk(factory) if isinstance(n, ast.FunctionDef) and n.name == "build_run_inspector")
        names = {n.func.id for n in ast.walk(builder) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert not names & {"DeviceInteractor", "DriverGatewayInteractor", "OpentronsSessionFactory"}
        assert ".register(snapshot)" not in (SRC / "bootstrap.py").read_text()

    def test_material_registration_has_no_vendor_result_codes(self):
        for path in (SRC / "material_system").rglob("*.py"):
            assert "DRV_OT" not in path.read_text(), path

