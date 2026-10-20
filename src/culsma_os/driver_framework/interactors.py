from .models import (
    DeviceExecutionPort,
    PreparedDevicePlan,
    DeviceReceiptMapper,
    CompilationPort,
)
from culsma_os.device_manager.models import DeviceAccessPort
from contextlib import contextmanager
from importlib.metadata import entry_points
from typing import Iterator, cast
from culsma_os.workspace_manager.models import MotionDevicePort
from culsma.driver.base import Driver
from culsma.driver.stub import StubDriver
from .models import DriverBuildContext, DriverFactory, DriverLoadError


class DriverGatewayInteractor:

    def __init__(
        self,
        port: DeviceExecutionPort,
        device: DeviceAccessPort,
        receipt_mapper: DeviceReceiptMapper,
        reservations=None,
    ):
        self.port = port
        self.device = device
        self.receipt_mapper = receipt_mapper
        self.reservations = reservations
        self.feedback = FeedbackContractInteractor(device)

    def prepare(self, effect_id, intent, context, bindings, completion_unit="operation"):
        self.device.validate_ready(context)
        self.feedback.require_unit(context, completion_unit)
        self.require_selection(intent, context)
        self.validate_material(context, bindings)
        vendor_plan = self.port.prepare(intent, bindings)
        return PreparedDevicePlan(
            effect_id, intent, context, vendor_plan,
            self.feedback.freeze(self.port.describe(vendor_plan), context, completion_unit, (intent.step_id,))
        )

    def prepare_processing(self, effect_id, intent, context, bindings):
        self.device.validate_ready(context)
        self.feedback.require_unit(context, "operation")
        vendor_plan = self.port.prepare_processing(intent, bindings)
        return PreparedDevicePlan(effect_id, intent, context, vendor_plan,
            self.feedback.freeze(self.port.describe_processing(vendor_plan), context, "operation", (intent.step_id,)))

    def prepare_motion(self, effect_id, intent, context):
        self.device.validate_ready(context)
        self.feedback.require_unit(context, "operation")
        motion = cast(MotionDevicePort, self.port)
        vendor_plan = motion.prepare_labware_move(intent)
        description = motion.describe_labware_move(vendor_plan)
        from dataclasses import asdict
        description = {**description, "operation_kind": "labware_move", "motion_intent": asdict(intent)}
        return PreparedDevicePlan(effect_id, intent, context, vendor_plan,
            self.feedback.freeze(description, context, "operation", (intent.step_id,)))

    def execute(self, plan, permit, attempt_id):
        with self.dispatch_guard(permit, plan.context.run_id):
            if (
                permit.effect_id != plan.effect_id
                or permit.attempt_id != attempt_id
                or permit.resources != plan.context.resource_ids
            ):
                raise ValueError("DRIVER_PERMIT_MISMATCH")
            self.device.validate_ready(plan.context)
            self.feedback.validate_current(plan)
            return self.feedback.normalize(plan, self.receipt_mapper.map(
                plan, self.port.execute(plan.vendor_plan, attempt_id)
            ))

    def execute_group_member(self, group, member, permit, group_attempt_id, member_attempt_id):
        with self.dispatch_guard(permit, group.context.run_id):
            if (permit.effect_id != group.effect_id or permit.attempt_id != group_attempt_id
                    or permit.resources != group.context.resource_ids
                    or member not in group.members or member.context != group.context):
                raise ValueError("DRIVER_GROUP_PERMIT_MISMATCH")
            self.device.validate_ready(member.context)
            self.feedback.validate_current(member)
            return self.feedback.normalize(member, self.receipt_mapper.map(member, self.port.execute(member.vendor_plan, member_attempt_id)))

    @property
    def supports_collective_execution(self):
        return getattr(self.port, "supports_collective_execution", False) is True

    def prepare_collective_group(self, effect_id, step_id, member_effect_ids, intents, context, bindings):
        from .models import PreparedTransferGroup
        from culsma_os.transfer_engine.models import TransferGroupIntent
        self.device.validate_ready(context)
        self.validate_material(context, bindings)
        self.feedback.require_unit(context, "batch")
        for intent in intents:
            self.require_selection(intent, context)
        vendor_plan = self.port.prepare_group(step_id, intents, bindings)
        description = self.port.describe_group(vendor_plan)
        if (description.get("member_step_ids") != [i.step_id for i in intents]
                or len(description.get("member_descriptions", [])) != len(intents)):
            raise ValueError("COLLECTIVE_PLAN_COVERAGE_INVALID")
        members = tuple(PreparedDevicePlan(identity, intent, context, None, member_description)
                        for identity, intent, member_description in
                        zip(member_effect_ids, intents, description["member_descriptions"]))
        waves = []
        if description.get("waves"):
            from .models import PreparedDeviceWave
            self.feedback.require_unit(context, "wave")
            specs = description["waves"]
            vendor_waves = self.port.wave_plans(vendor_plan)
            flattened = [i for wave in specs for i in wave["member_step_ids"]]
            if (len(specs) != len(vendor_waves) or len(flattened) != len(members)
                    or len(set(flattened)) != len(members) or set(flattened) != {i.step_id for i in intents}
                    or len({wave["step_id"] for wave in specs}) != len(specs)
                    or any(len(wave["member_step_ids"]) != 8 for wave in specs)):
                raise ValueError("COLLECTIVE_WAVE_COVERAGE_INVALID")
            by_step = {m.intent.step_id: m for m in members}
            ordinal = {m.intent.step_id: i for i, m in enumerate(members)}
            requirements = {}
            for index, (spec, wave_plan) in enumerate(zip(specs, vendor_waves)):
                selected = tuple(by_step[i] for i in spec["member_step_ids"])
                if spec.get("semantic_ordinals") != [ordinal[i] for i in spec["member_step_ids"]]:
                    raise ValueError("COLLECTIVE_WAVE_ORDINAL_INVALID")
                for resource, count in spec.get("resource_requirements", {}).items():
                    if not isinstance(resource, str) or type(count) is not int or count < 0:
                        raise ValueError("COLLECTIVE_WAVE_RESOURCES_INVALID")
                    requirements[resource] = requirements.get(resource, 0) + count
                waves.append(PreparedDeviceWave(f"{effect_id}/wave/{index}",
                    TransferGroupIntent(spec["step_id"], tuple(m.intent for m in selected)), context, selected,
                    self.feedback.freeze({**spec, "collective": True, "member_effect_ids": [m.effect_id for m in selected]},
                        context, "wave", tuple(m.intent.step_id for m in selected)), wave_plan))
            if requirements != description["resource_requirements"]:
                raise ValueError("COLLECTIVE_WAVE_RESOURCES_INVALID")
            description = {**description, "waves": [{**w.description, "effect_id": w.effect_id} for w in waves]}
        return PreparedTransferGroup(effect_id, TransferGroupIntent(step_id, intents), context, members,
            self.feedback.freeze({**description, "collective": True, "member_effect_ids": list(member_effect_ids)},
                context, "batch", tuple(i.step_id for i in intents)), vendor_plan, tuple(waves))

    def execute_collective_group(self, group, permit, attempt_id):
        with self.dispatch_guard(permit, group.context.run_id):
            if (permit.effect_id != group.effect_id or permit.attempt_id != attempt_id
                    or permit.resources != group.context.resource_ids or group.vendor_plan is None):
                raise ValueError("DRIVER_GROUP_PERMIT_MISMATCH")
            self.device.validate_ready(group.context)
            self.feedback.validate_current(group)
            receipt = self.feedback.normalize(group, self.receipt_mapper.map(group, self.port.execute_group(group.vendor_plan, attempt_id)))
            if receipt.outcome == "completed" and receipt.payload.get("member_step_ids") != [m.intent.step_id for m in group.members]:
                from dataclasses import replace
                return replace(receipt, outcome="unknown")
            return receipt

    def execute_group_wave(self, group, wave, permit, group_attempt_id, wave_attempt_id):
        with self.dispatch_guard(permit, group.context.run_id):
            if (permit.effect_id != group.effect_id or permit.attempt_id != group_attempt_id
                    or permit.resources != group.context.resource_ids or wave not in group.waves
                    or wave.context != group.context):
                raise ValueError("DRIVER_GROUP_WAVE_PERMIT_MISMATCH")
            self.device.validate_ready(group.context)
            self.feedback.validate_current(wave)
            receipt = self.feedback.normalize(wave, self.receipt_mapper.map(wave,
                self.port.execute_group_wave(group.vendor_plan, wave.vendor_plan, wave_attempt_id)))
            if receipt.outcome == "completed" and receipt.payload.get("member_step_ids") != [m.intent.step_id for m in wave.members]:
                from dataclasses import replace
                return replace(receipt, outcome="unknown")
            return receipt

    def dispatch_guard(self, permit, run_id):
        from contextlib import nullcontext
        return self.reservations.permit_guard(permit, run_id) if self.reservations else nullcontext()

    def require_selection(self, intent, context):
        from culsma_os.transfer_engine.interactors import TransferConstraintInteractor
        TransferConstraintInteractor().require_supported(intent.requirements, self.device.get(context.device_id))
        if self.device.get(context.device_id).supports_transfer is False:
            raise ValueError("TRANSFER_DEVICE_UNSUPPORTED")
        kind = getattr(intent, "selection_kind", None)
        if kind is not None and kind not in self.device.get(context.device_id).transfer_selection_capabilities:
            raise ValueError("DRIVER_TRANSFER_SELECTION_UNSUPPORTED")

    def validate_material(self, context, bindings):
        validator = getattr(self.port, "validate_material", None)
        if callable(validator):
            validator(context.expected_material, bindings)

    def close(self):
        self.port.close()


class HamiltonCompilationInteractor:

    def __init__(self, port: CompilationPort):
        self.port = port

    def compile(self, request):
        from .models import CompilationEvidence

        return CompilationEvidence(self.port.compile(request))


class NormalizedReceiptInteractor:
    """Validate generic device feedback against the authorized plan identity."""

    def map(self, plan, payload):
        from copy import deepcopy
        from .models import DeviceReceipt

        value = payload if isinstance(payload, dict) else {}
        consumption = value.get("consumed_resources", {})
        valid_consumption = isinstance(consumption, dict) and all(
            isinstance(k, str) and type(v) is int and v >= 0
            for k, v in consumption.items()
        )
        matches = (
            value.get("mode") == plan.context.mode
            and value.get("configuration_revision")
            == plan.context.configuration_revision
            and value.get("step_id") == plan.intent.step_id
            and isinstance(value.get("payload"), dict)
            and valid_consumption
            and ("execution_status" not in value
                 or not isinstance(value.get("payload"), dict)
                 or "execution_status" not in value["payload"]
                 or value["execution_status"] == value["payload"]["execution_status"])
        )
        outcome = value.get("outcome") if matches else "unknown"
        if outcome not in ("completed", "rejected", "unknown"):
            outcome = "unknown"
        details = deepcopy(value.get("payload", value))
        if not isinstance(details, dict):
            details = {}
        if "execution_status" in value:
            details["execution_status"] = deepcopy(value["execution_status"])
        elif value.get("outcome") not in ("completed", "rejected", "unknown"):
            details["execution_status"] = deepcopy(value.get("outcome", "unknown"))
        return DeviceReceipt(
            outcome,
            plan.context.mode,
            plan.intent.step_id,
            plan.context.configuration_revision,
            details,
            deepcopy(consumption) if valid_consumption else {},
        )


class DriverLoaderInteractor:
    def load_factory(self, name: str) -> DriverFactory:
        candidates = list(entry_points(group="culsma.drivers", name=name))
        if not candidates:
            raise DriverLoadError(
                f"DRIVER_NOT_INSTALLED: '{name}'; install its package in the same Python environment as culsma"
            )
        if len(candidates) != 1:
            raise DriverLoadError(
                f"DRIVER_NAME_CONFLICT: multiple installed drivers named '{name}'"
            )
        try:
            factory = candidates[0].load()()
        except Exception as error:
            raise DriverLoadError(f"DRIVER_LOAD_FAILED: '{name}': {error}") from error
        if not callable(getattr(factory, "open", None)):
            raise DriverLoadError(
                f"DRIVER_FACTORY_INVALID: '{name}' must provide open(context)"
            )
        return factory

    @contextmanager
    def open_session(self, name: str, context: DriverBuildContext) -> Iterator[Driver]:
        if name == "stub":
            if context.config_path is not None:
                raise DriverLoadError(
                    "DRIVER_CONFIG_UNSUPPORTED: builtin stub has no configuration file"
                )
            yield StubDriver(fail_ops=set(context.fail_ops))
            return
        if context.fail_ops:
            raise DriverLoadError(
                "DRIVER_OPTION_UNSUPPORTED: --fail-op is only supported by stub"
            )
        factory = self.load_factory(name)
        try:
            manager = factory.open(context)
            driver = manager.__enter__()
        except Exception as error:
            raise DriverLoadError(f"DRIVER_SETUP_FAILED: '{name}': {error}") from error
        try:
            if not all(
                callable(getattr(driver, method, None))
                for method in ("check", "execute")
            ):
                raise DriverLoadError(
                    f"DRIVER_INSTANCE_INVALID: '{name}' must implement check/execute"
                )
            yield driver
        except BaseException as error:
            manager.__exit__(type(error), error, error.__traceback__)
            raise
        else:
            manager.__exit__(None, None, None)


class FeedbackContractInteractor:
    """Bind completion claims to the authorized submitted unit, not log detail."""

    def __init__(self, device):
        self.device = device

    def capability(self, context):
        from culsma_os.device_manager.models import ExecutionFeedbackCapabilities
        value = self.device.get(context.device_id).feedback_capabilities
        if value is not None and not isinstance(value, ExecutionFeedbackCapabilities):
            raise ValueError("FEEDBACK_CAPABILITIES_INVALID")
        return value

    def require_unit(self, context, unit):
        capability = self.capability(context)
        if unit not in ("operation", "member", "batch", "wave") or (capability is not None and unit not in capability.completion_units):
            raise ValueError("FEEDBACK_UNIT_UNSUPPORTED")

    def freeze(self, description, context, unit, step_ids):
        from dataclasses import asdict
        self.require_unit(context, unit)
        capability = self.capability(context)
        return {**description, "feedback_contract": {
            "schema": "culsma_feedback_contract_v1",
            "capabilities": asdict(capability) if capability is not None else None,
            "completion_unit": unit, "covered_step_ids": list(step_ids),
        }}

    def validate_current(self, plan):
        from dataclasses import asdict
        contract = plan.description.get("feedback_contract")
        capability = self.capability(plan.context)
        if contract is None:
            if capability is not None:
                raise ValueError("FEEDBACK_CONTRACT_STALE")
            return  # Legacy manually constructed plan, no finer-grained claims.
        current = asdict(capability) if capability is not None else None
        if contract["capabilities"] != current:
            raise ValueError("FEEDBACK_CONTRACT_STALE")
        self.require_unit(plan.context, contract["completion_unit"])

    def normalize(self, plan, receipt):
        from copy import deepcopy
        from dataclasses import replace
        contract = plan.description.get("feedback_contract", {
            "capabilities": None, "completion_unit": "operation",
            "covered_step_ids": [plan.intent.step_id],
        })
        payload = deepcopy(receipt.payload)
        status = payload.get("execution_status", receipt.outcome)
        reason = None
        if status not in ("completed", "rejected", "unknown", "prepared", "not_submitted",
                          "submitted", "accepted", "running") or status != receipt.outcome:
            reason = "FEEDBACK_STATUS_INVALID"
        if payload.get("completion_unit", contract["completion_unit"]) != contract["completion_unit"]:
            reason = "FEEDBACK_UNIT_MISMATCH"
        if payload.get("covered_step_ids", contract["covered_step_ids"]) != contract["covered_step_ids"]:
            reason = "FEEDBACK_COVERAGE_INVALID"
        payload["os_feedback"] = {
            "execution_status": status,
            "completion_unit": contract["completion_unit"],
            "covered_step_ids": list(contract["covered_step_ids"]),
            "capabilities_declared": contract["capabilities"] is not None,
            "diagnostic": reason,
        }
        return replace(receipt, outcome="unknown" if reason else receipt.outcome, payload=payload)


class DriverProfileInteractor:
    """Optional configuration capability on installed driver factories."""
    def __init__(self, candidates=None, configuration_candidates=None):
        self.candidates = candidates
        self.configuration_candidates = configuration_candidates

    def discover(self):
        candidates = self.candidates if self.candidates is not None else entry_points(group='culsma.drivers')
        profiles, unavailable = {}, []
        for candidate in candidates:
            try:
                factory = candidate.load()()
                capability = getattr(factory,'configuration_profile',None)
                if not callable(capability):
                    continue
                if candidate.name in profiles:
                    raise ValueError('PROFILE_NAME_CONFLICT')
                profiles[candidate.name] = capability()
            except Exception:
                unavailable.append(candidate.name)
        # Offline configuration plugins need not pretend to be executable drivers.
        standalone = (self.configuration_candidates if self.configuration_candidates is not None
                      else entry_points(group='culsma.configuration_profiles') if self.candidates is None else ())
        for candidate in standalone:
            try:
                if candidate.name in profiles:
                    raise ValueError('PROFILE_NAME_CONFLICT')
                profiles[candidate.name] = candidate.load()()
            except Exception:
                unavailable.append(candidate.name)
        for name in unavailable:
            profiles.pop(name,None)
        return profiles, tuple(unavailable)
