"""Keep execution mode decisions in one OS Interactor, independent of vendors."""
import ast

from tests.support.architecture.architecture import SRC


class TestExecutionStrategyArchitecture:
    def test_only_the_scheduler_strategy_reads_execution_modes(self):
        owner = SRC / "scheduler/interactors.py"
        for path in SRC.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ExecutionMode":
                    assert path == owner, path
                    strategy = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "ExecutionStrategyInteractor")
                    assert node in list(ast.walk(strategy)), path

    def test_lifecycle_delegates_advancement_without_selecting_a_mode(self):
        tree = ast.parse((SRC / "lifecycle_manager/interactors.py").read_text())
        lifecycle = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LifecycleInteractor")
        advance = next(node for node in lifecycle.body if isinstance(node, ast.FunctionDef) and node.name == "advance_once")
        calls = [node.func for node in ast.walk(advance) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        assert not any(call.attr in {"dispatch_ready", "advance_ready", "execute_stepwise"} for call in calls)
        assert sum(call.attr == "execute" and isinstance(call.value, ast.Attribute)
                   and call.value.attr == "execution_strategy" for call in calls) == 1

    def test_strategy_uses_public_interactors_without_vendor_or_storage_access(self):
        tree = ast.parse((SRC / "scheduler/interactors.py").read_text())
        strategy = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ExecutionStrategyInteractor")
        text = ast.unparse(strategy)
        assert not any(value in text for value in ["culsma_driver_hamilton", "culsma_opentrons", ".repository", ".checkpoint", ".resume("])
        assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(strategy))
        ports = ast.parse((SRC / "scheduler/models.py").read_text())
        port = next(node for node in ports.body if isinstance(node, ast.ClassDef) and node.name == "RunExecutionPort")
        assert [node.name for node in port.body if isinstance(node, ast.FunctionDef)] == ["execute"]
