from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import ast
import pytest
from culsma_os.driver_framework import interactors as loading


def context(**values):
    return loading.DriverBuildContext(plan=None, state=None, **values)


def install(monkeypatch, factory):
    monkeypatch.setattr(
        loading,
        "entry_points",
        lambda **kwargs: [SimpleNamespace(load=lambda: factory)],
    )
