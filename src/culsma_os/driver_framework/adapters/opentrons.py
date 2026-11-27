"""OS boundary DTO conversion only; all vendor behavior belongs to the plugin."""

from dataclasses import asdict
from culsma_opentrons.modules.models import TemperatureTargetVolume, TemperatureHoldIntent, PreparedTemperatureHold, OrbitalShakeIntent as VendorShakeIntent, PreparedOrbitalShake
from culsma_os.device_manager.instruments.execution_models import CentrifugeIntent, ThermalHoldIntent, OrbitalShakeIntent, MagneticSeparationIntent, MagneticReleaseIntent
from culsma_os.device_manager.instruments.pipetting.models import (
    CentrifugeFractionTransferIntent, CentrifugeSupernatantTransferIntent, MagneticFlowthroughTransferIntent,
)
from culsma_opentrons.modules.models import MagneticSeparationIntent as VendorMagneticIntent, MagneticReleaseIntent as VendorReleaseIntent, PreparedMagneticOperation, MagneticSourceSelection
from culsma_opentrons.models import SimulatorBinding, WellAddress, DriverValidationError
from culsma_os.driver_framework.models import DevicePreparationError
from culsma_opentrons.operations import (
    ResolvedContainerRef,
    TransferAliquot,
    TransferIntent,
)


class OpentronsSessionAdapter:
    """Convert OS configuration at the vendor boundary before opening a session."""

    def create(self, configuration, artifacts_dir, *, state_dir=None):
        from culsma_opentrons.config import DeckConfiguration
        from culsma_opentrons.plugin import SimulatorSessionFactory

        return SimulatorSessionFactory().create(
            DeckConfiguration.from_dict(configuration), artifacts_dir, state_dir=state_dir)


class OpentronsExecutionAdapter:
    def __init__(self, session):
        self.session = session

    def prepare(self, intent, bindings):
        try:
            if isinstance(intent, CentrifugeSupernatantTransferIntent):
                return self.session.prepare_centrifuge_supernatant(
                    self.convert_intent(intent), self.convert_bindings(bindings), intent.producer_step_id,
                )
            if isinstance(intent, CentrifugeFractionTransferIntent):
                raise DevicePreparationError("OPENTRONS_CENTRIFUGE_FRACTION_UNSUPPORTED", "Only supernatant transfer is supported")
            if isinstance(intent, MagneticFlowthroughTransferIntent):
                return self.session.prepare_magnetic_transfer(self.convert_intent(intent),
                    tuple(SimulatorBinding(ResolvedContainerRef(b.reference.container_id), WellAddress(b.labware, b.well)) for b in bindings),
                    MagneticSourceSelection(intent.aliquots[0].source.container_id, intent.producer_step_id))
            return self.session.prepare_transfer(
                self.convert_intent(intent),
                tuple(
                    SimulatorBinding(
                        ResolvedContainerRef(b.reference.container_id),
                        WellAddress(b.labware, b.well),
                    )
                    for b in bindings
                ),
            )
        except DriverValidationError as error:
            raise DevicePreparationError(error.code, str(error)) from error

    def convert_intent(self, intent):
        return TransferIntent(
            intent.step_id,
            ResolvedContainerRef(intent.target.container_id),
            tuple(
                TransferAliquot(
                    ResolvedContainerRef(a.source.container_id), a.volume_uL
                )
                for a in intent.aliquots
            ),
            intent.span,
            intent.requirements,
            intent.constraint_options,
            intent.environment_requirements,
        )

    @staticmethod
    def convert_bindings(bindings):
        return tuple(
            SimulatorBinding(ResolvedContainerRef(binding.reference.container_id),
                             WellAddress(binding.labware, binding.well))
            for binding in bindings
        )

    def prepare_centrifuge(self, intent, bindings):
        from culsma_opentrons.centrifuge import CentrifugeIntent as DeviceCentrifugeIntent, DriveUnit

        conditions = intent.environment_conditions
        if conditions and (len(conditions) != 1 or (conditions[0].name, conditions[0].unit) != ("thermal", "C")):
            raise DevicePreparationError(
                "OPENTRONS_CENTRIFUGE_ENVIRONMENT_UNSUPPORTED", "Only one Celsius temperature condition is supported"
            )
        try:
            request = DeviceCentrifugeIntent(
                intent.step_id, tuple(ResolvedContainerRef(t.container_id) for t in intent.targets),
                intent.drive_value, DriveUnit(intent.drive_unit), intent.duration_seconds,
                conditions[0].value if conditions else None,
            )
        except ValueError as error:
            raise DevicePreparationError("OPENTRONS_CENTRIFUGE_REQUEST_INVALID", str(error)) from error
        return self.session.prepare_centrifuge(request, self.convert_bindings(bindings))

    def is_centrifuge_plan(self, plan):
        if not getattr(self.session, "centrifuges", None):
            return False
        from culsma_opentrons.centrifuge.models import PreparedCentrifuge
        return isinstance(plan, PreparedCentrifuge)

    def describe(self, plan):
        return self.session.describe_transfer(plan)

    def prepare_processing(self, intent, bindings):
        try:
            if isinstance(intent, CentrifugeIntent):
                return self.prepare_centrifuge(intent, bindings)
            if isinstance(intent, (MagneticSeparationIntent, MagneticReleaseIntent)):
                vendor_intent = (VendorMagneticIntent(intent.step_id, tuple(ResolvedContainerRef(t.container_id) for t in intent.targets), intent.duration_seconds)
                    if isinstance(intent, MagneticSeparationIntent) else VendorReleaseIntent(intent.step_id, tuple(ResolvedContainerRef(t.container_id) for t in intent.targets), intent.producer_step_id))
                return self.session.prepare_magnetic_separation(vendor_intent,
                    tuple(SimulatorBinding(ResolvedContainerRef(b.reference.container_id), WellAddress(b.labware, b.well)) for b in bindings))
            if isinstance(intent, OrbitalShakeIntent):
                shake_parameters = {}
                if intent.environment_conditions:
                    conditions = intent.environment_conditions
                    if len(conditions) != 1 or (conditions[0].name, conditions[0].unit) != ("thermal", "C"):
                        raise DevicePreparationError("OPENTRONS_SHAKE_ENVIRONMENT_UNSUPPORTED",
                            "Heater-Shaker supports a single temperature setpoint")
                    shake_parameters["temperature_celsius"] = conditions[0].value
                return self.session.prepare_orbital_shake(
                    VendorShakeIntent(intent.step_id, tuple(ResolvedContainerRef(t.container_id) for t in intent.targets),
                                      intent.rate_rpm, intent.duration_seconds, **shake_parameters),
                    tuple(SimulatorBinding(ResolvedContainerRef(b.reference.container_id), WellAddress(b.labware, b.well)) for b in bindings))
            if not isinstance(intent, ThermalHoldIntent):
                raise DevicePreparationError("OPENTRONS_PROCESSING_UNSUPPORTED", "Unsupported processing request")
            return self.session.prepare_temperature_hold(
                TemperatureHoldIntent(intent.step_id, tuple(ResolvedContainerRef(t.container_id) for t in intent.targets),
                                      intent.temperature_celsius, intent.duration_seconds,
                                      tuple(TemperatureTargetVolume(ResolvedContainerRef(v.reference.container_id), v.volume_uL)
                                            for v in intent.material_volumes)),
                tuple(SimulatorBinding(ResolvedContainerRef(b.reference.container_id), WellAddress(b.labware, b.well)) for b in bindings))
        except DriverValidationError as error:
            raise DevicePreparationError(error.code, str(error)) from error

    def describe_processing(self, plan):
        if self.is_centrifuge_plan(plan):
            return self.session.describe_centrifuge(plan)
        if isinstance(plan, PreparedMagneticOperation):
            return self.session.describe_magnetic_operation(plan)
        if isinstance(plan, PreparedOrbitalShake):
            return self.session.describe_orbital_shake(plan)
        return self.session.describe_temperature_hold(plan)

    def prepare_labware_move(self, intent):
        from culsma_opentrons.motion.models import LabwareMoveIntent as VendorMoveIntent
        try:
            return self.session.prepare_labware_move(VendorMoveIntent(intent.step_id, intent.labware, intent.source, intent.destination, intent.position_revision))
        except DriverValidationError as error:
            raise DevicePreparationError(error.code, str(error)) from error

    def describe_labware_move(self, plan):
        return self.session.describe_labware_move(plan)

    def execute(self, plan, attempt_id):
        if self.is_centrifuge_plan(plan):
            return asdict(self.session.execute_centrifuge(plan))
        if getattr(self.session, "motion", None) is not None:
            from culsma_opentrons.motion.models import PreparedLabwareMove
            if isinstance(plan, PreparedLabwareMove):
                return asdict(self.session.execute_labware_move(plan))
        if isinstance(plan, PreparedMagneticOperation):
            return asdict(self.session.execute_magnetic_operation(plan))
        if isinstance(plan, PreparedOrbitalShake):
            return asdict(self.session.execute_orbital_shake(plan))
        if isinstance(plan, PreparedTemperatureHold):
            return asdict(self.session.execute_temperature_hold(plan))
        return asdict(self.session.execute_transfer(plan))

    def check_ready(self):
        self.session.check_ready()

    def close(self):
        self.session.close()

    def restore_consumables(self, consumption):
        self.session.restore_consumables(consumption)


    @property
    def supports_collective_execution(self):
        return self.session.supports_collective_execution

    def prepare_group(self, group_id, intents, bindings):
        try:
            return self.session.prepare_group(group_id, tuple(self.convert_intent(i) for i in intents),
                tuple(SimulatorBinding(ResolvedContainerRef(b.reference.container_id),
                                       WellAddress(b.labware, b.well)) for b in bindings))
        except DriverValidationError as error:
            raise DevicePreparationError(error.code, str(error)) from error

    def describe_group(self, plan):
        return self.session.describe_group(plan)

    def execute_group(self, plan, attempt_id):
        return asdict(self.session.execute_group(plan))


    def wave_plans(self, prepared):
        return self.session.wave_plans(prepared)

    def execute_group_wave(self, prepared, wave, attempt_id):
        return asdict(self.session.execute_group_wave(prepared, wave))
