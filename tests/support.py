from dataclasses import dataclass
from pathlib import Path
from culsma.frontend.resolver import resolve_files
from culsma.pipeline.compile import compile_ast
from culsma.pipeline.validate import validate
from culsma.pipeline.typecheck import typecheck
from culsma.pipeline.entrypoints import resolve_entry
from culsma.pipeline.plan import lower_ir_to_plan
from culsma.runtime.state import init_state
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.device_manager.models import DeviceConfigurationSnapshot
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from culsma_os.driver_framework.interactors import NormalizedReceiptInteractor


class ProgramFixture:
    source = Path(__file__).resolve().parents[1] / "examples/transfer/transfer.culs"

    @classmethod
    def request(cls):
        compiled = compile_ast(resolve_files([cls.source]).prepared_program)
        checked = validate(
            compiled.ir, analysis=compiled.analysis, enforce_binding=True
        )
        typed = typecheck(checked.ir, analysis=compiled.analysis)
        assert checked.ok and typed.ok
        plan = lower_ir_to_plan(
            typed.ir,
            analysis=compiled.analysis,
            entry_resolution=resolve_entry(typed.ir),
        )
        return RunRequest(plan, init_state(plan))


@dataclass(frozen=True)
class TestAddress:
    labware: str
    well: str


TestAddress.__test__ = False


class FakeDevicePort:

    def __init__(self):
        self.executions = []
        self.remaining = 96
        self.closed = False

    def check_ready(self):
        pass

    def restore_consumables(self, count):
        self.remaining = 96 - count.get("tips", 0)

    def require_consumables(self, count):
        if count > self.remaining:
            raise ValueError("TIPS_INSUFFICIENT")

    def prepare(self, intent, bindings):
        return intent

    def describe(self, intent):
        return {
            "resource_requirements": {"tips": len(intent.aliquots)},
            "transfers": [
                {
                    "stroke_id": f"{intent.step_id}/{i}",
                    "source": {"id": a.source.container_id},
                    "target": {"id": intent.target.container_id},
                    "volume_uL": a.volume_uL,
                }
                for i, a in enumerate(intent.aliquots)
            ],
        }

    def execute(self, plan, attempt_id):
        self.executions.append(attempt_id)
        commands = self.describe(plan)["transfers"]
        self.remaining -= len(commands)
        return {
            "outcome": "completed",
            "mode": "simulation",
            "step_id": plan.step_id,
            "configuration_revision": "r1",
            "consumed_resources": {"tips": len(commands)},
            "payload": {"source": "fake-device", "transfers": commands},
        }

    def close(self):
        self.closed = True


class FakeSessionFactory:

    def __init__(self):
        self.ports = []

    def build(self, context):
        port = FakeDevicePort()
        self.ports.append(port)
        return (
            port,
            DeviceConfigurationSnapshot(
                "fake",
                "simulation",
                "r1",
                ("simulation:fake:gantry",),
                consumable_capacities={"tips": 96},
            ),
            {
                "entry.s0::alloc": TestAddress("tubes", "A1"),
                "entry.s1::alloc": TestAddress("tubes", "A2"),
            },
            {("tubes", "A1"): 2000, ("tubes", "A2"): 2000},
            NormalizedReceiptInteractor(),
        )

    def open(self, tmp_path):
        return OSApplicationFactory({"fake": self}).build(
            HostBuildContext(
                tmp_path / "os.sqlite3", "fake", None, tmp_path / "artifacts"
            )
        )
