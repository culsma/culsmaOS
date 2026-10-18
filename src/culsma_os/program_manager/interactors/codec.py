"""JSON checkpoint codec with an explicit core type allowlist; never imports input types."""

from dataclasses import fields, is_dataclass
from hashlib import sha256
import json
from culsma.domains.separation import CentrifugeProgramOutput
from culsma.common.source import Span
from culsma.common.diagnostics import Diagnostic
from culsma.pipeline.plan_nodes import PlanProgram, PlanStep, ProtocolPlan
from culsma.runtime.state import RuntimeState
from culsma.runtime.event_log import RuntimeEvent
from culsma.runtime.material.accounting import (
    MaterialAccounting,
    InputLot,
    MaterialQuantity,
    MaterialMovement,
)
from culsma.runtime.material.result import MaterialUpdateResult, MaterialMovementSpec
from culsma.runtime.executor import RunResult
from ..models import (
    PreparedRuntimeStep,
    PendingEffect,
    HostContractError,
    EffectResolution,
    RecordedEffect,
    HostedRunResult,
    PendingEffectGroup, GroupEffectResolution, RecordedEffectGroup,
)


class RuntimeCheckpointCodecInteractor:
    enum_types = {CentrifugeProgramOutput.__name__: CentrifugeProgramOutput}

    types = {
        c.__name__: c
        for c in (
            Span,
            Diagnostic,
            PlanProgram,
            PlanStep,
            ProtocolPlan,
            RuntimeState,
            RuntimeEvent,
            MaterialAccounting,
            InputLot,
            MaterialQuantity,
            MaterialMovement,
            MaterialUpdateResult,
            MaterialMovementSpec,
            PreparedRuntimeStep,
            PendingEffect,
            EffectResolution,
            RecordedEffect,
            RunResult,
            HostedRunResult,
            PendingEffectGroup, GroupEffectResolution, RecordedEffectGroup,
        )
    }

    def encode(self, value):
        cls = self.enum_types.get(type(value).__name__)
        if cls is type(value):
            return {"t": "enum", "c": cls.__name__, "v": value.name}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if (
            is_dataclass(value)
            and type(value).__name__ in self.types
            and self.types[type(value).__name__] is type(value)
        ):
            return {
                "t": "object",
                "c": type(value).__name__,
                "v": {
                    f.name: self.encode(getattr(value, f.name)) for f in fields(value)
                },
            }
        if isinstance(value, dict) and all(isinstance(k, str) for k in value):
            return {"t": "map", "v": {k: self.encode(v) for k, v in value.items()}}
        if isinstance(value, (list, tuple)):
            return {
                "t": "tuple" if isinstance(value, tuple) else "list",
                "v": [self.encode(v) for v in value],
            }
        raise HostContractError(
            f"HOST_CHECKPOINT_TYPE_UNSUPPORTED: {type(value).__name__}"
        )

    def decode(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if not isinstance(value, dict) or set(value) - {"t", "c", "v"}:
            raise HostContractError("HOST_CHECKPOINT_INVALID")
        if value.get("t") == "enum":
            cls = self.enum_types.get(value.get("c"))
            if cls is None or not isinstance(value.get("v"), str):
                raise HostContractError("HOST_CHECKPOINT_TYPE_UNSUPPORTED")
            try:
                return cls[value["v"]]
            except KeyError as error:
                raise HostContractError("HOST_CHECKPOINT_ENUM_INVALID") from error
        if value.get("t") == "object":
            cls = self.types.get(value.get("c"))
            if cls is None or not isinstance(value.get("v"), dict):
                raise HostContractError("HOST_CHECKPOINT_TYPE_UNSUPPORTED")
            return cls(**{k: self.decode(v) for k, v in value["v"].items()})
        if value.get("t") == "map":
            return {k: self.decode(v) for k, v in value["v"].items()}
        if value.get("t") in {"list", "tuple"}:
            decoded = [self.decode(v) for v in value["v"]]
            return tuple(decoded) if value["t"] == "tuple" else decoded
        raise HostContractError("HOST_CHECKPOINT_INVALID")

    def dumps(self, value):
        return json.dumps(
            self.encode(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    def loads(self, text):
        return self.decode(json.loads(text))

    def fingerprint(self, value):
        return sha256(self.dumps(value).encode()).hexdigest()
