from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import ast
import pytest
from culsma_os.driver_framework import interactors as loading
from tests.support.driver_framework.driver_loading import context, install


def test_unknown_driver(monkeypatch):
    monkeypatch.setattr(loading, "entry_points", lambda **kwargs: [])
    with pytest.raises(loading.DriverLoadError, match="DRIVER_NOT_INSTALLED"):
        loading.DriverLoaderInteractor().load_factory("missing")


def test_duplicate_driver(monkeypatch):
    monkeypatch.setattr(loading, "entry_points", lambda **kwargs: [None, None])
    with pytest.raises(loading.DriverLoadError, match="DRIVER_NAME_CONFLICT"):
        loading.DriverLoaderInteractor().load_factory("duplicate")


def test_factory_load_failure(monkeypatch):
    def fail():
        raise ImportError("optional dependency absent")

    monkeypatch.setattr(
        loading, "entry_points", lambda **kwargs: [SimpleNamespace(load=fail)]
    )
    with pytest.raises(loading.DriverLoadError, match="DRIVER_LOAD_FAILED"):
        loading.DriverLoaderInteractor().load_factory("broken")


def test_session_closes_on_runtime_failure(monkeypatch):
    closed = []

    class Factory:
        @contextmanager
        def open(self, context):
            try:
                yield SimpleNamespace(
                    check=lambda step: None, execute=lambda step: None
                )
            finally:
                closed.append(True)

    install(monkeypatch, Factory)
    with pytest.raises(RuntimeError, match="runtime failed"):
        with loading.DriverLoaderInteractor().open_session("test", context()):
            raise RuntimeError("runtime failed")
    assert closed == [True]


def test_setup_failure(monkeypatch):
    class Factory:
        @contextmanager
        def open(self, context):
            raise ValueError("invalid deck")
            yield

    install(monkeypatch, Factory)
    with pytest.raises(loading.DriverLoadError, match="DRIVER_SETUP_FAILED"):
        with loading.DriverLoaderInteractor().open_session("test", context()):
            pytest.fail("must not run")


def test_stub_options():
    with pytest.raises(loading.DriverLoadError, match="DRIVER_CONFIG_UNSUPPORTED"):
        with loading.DriverLoaderInteractor().open_session(
            "stub", context(config_path=Path("deck.json"))
        ):
            pass
    with pytest.raises(loading.DriverLoadError, match="DRIVER_OPTION_UNSUPPORTED"):
        with loading.DriverLoaderInteractor().open_session(
            "plugin", context(fail_ops=frozenset({"Mutation"}))
        ):
            pass


def test_core_has_no_device_planning_contracts():
    import culsma

    root = Path(culsma.__file__).resolve().parent
    assert not (root / "driver/operations").exists()
    forbidden = (
        "culsma_opentrons",
        "culsma_driver_hamilton",
        "culsma_os",
        "culsma.driver.operations",
    )
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [
            n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        ]
        imports += [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        assert not any(m.startswith(forbidden) for m in imports), path

