"""with-sep must retain the source field through extraction and release it."""
from culsma.runtime.state import init_state
import pytest
from tests.support.processing_engine.processing_magnetic import MagneticFixture, DECLARATIONS


def test_with_sep_magnetic_scope_has_no_duplicate_env(tmp_path, monkeypatch):
    source = DECLARATIONS + '''sample << [stock];
      with sep(sample=sample,program=magnetic_program(duration=2min)) {
        waste << [sample.contents[1]:20uL];
        waste << [sample.contents[1]:20uL];
      }
      with sep(sample=sample,program=magnetic_program(duration=1min)) {
        waste << [sample.contents[1]:20uL];
      }
    '''
    plan, _, app = MagneticFixture().build(tmp_path, source)
    held_at_aspiration = []
    session = app.host.gateway.port.session
    original = session.backend.pipette.aspirate
    def observe(*args, **kwargs):
        held_at_aspiration.append(bool(session.magnetic.held))
        return original(*args, **kwargs)
    monkeypatch.setattr(session.backend.pipette, 'aspirate', observe)
    try:
        result = app.execute(plan, init_state(plan))
        MagneticFixture().compare(app, plan, result)
        receipts = app.host.gateway.port.session.magnetic.receipts
        assert [r.payload['operation_kind'] for r in receipts] == ['magnetic_separation', 'magnetic_release'] * 2
        assert [r.payload['request']['duration_seconds'] for r in receipts[::2]] == [120, 60]
        assert held_at_aspiration == [False, True, True, True]
        assert not app.host.gateway.port.session.magnetic.held
        assert all(not record['valid'] for record in result.state.artifacts['material_state']['contents_states'].values())
    finally:
        app.close()


def test_with_sep_centrifuge_uses_existing_device_method_contract(tmp_path):
    from tests.support.processing_engine.processing_centrifuge_separation import SeparationContractFixture, BASE, TRANSFER
    fixture = SeparationContractFixture()
    plan, _, app = fixture.open(tmp_path, BASE + 'with sep(sample=s,program=centrifuge_program(drive=500g)) {' + TRANSFER + '}return d;')
    try:
        result = app.execute(plan, init_state(plan))
        assert result.ok, result.diagnostics
        assert len(fixture.port.processing) == 1
        assert all(not record['valid'] for record in result.state.artifacts['material_state']['contents_states'].values())
    finally:
        app.close()


def test_centrifuge_env_duration_and_temperature_reach_device(tmp_path, monkeypatch):
    from dataclasses import replace
    from tests.support.processing_engine.processing_centrifuge_separation import SeparationContractFixture, BASE
    from culsma_os.device_manager.instruments.execution_models import EnvironmentCondition
    fixture = SeparationContractFixture(profile=None)
    original_build = fixture.build
    def build(context):
        port, snapshot, *rest = original_build(context)
        capabilities = {'centrifuge': {'rotor': {
            'labware': ['loaded'],
            'environment_conditions': {'thermal': {'unit': 'C', 'minimum': 0, 'maximum': 50}}
        }}}
        def prepare(intent, bindings):
            assert intent.duration_seconds == 120
            assert intent.environment_conditions == (EnvironmentCondition('thermal', 4, 'C'),)
            assert intent.method_profile is None
            return intent
        monkeypatch.setattr(port, 'prepare_processing', prepare)
        return port, replace(snapshot, processing_capabilities=capabilities), *rest
    monkeypatch.setattr(fixture, 'build', build)
    plan, _, app = fixture.open(tmp_path, BASE + 'with env(thermal=4C,duration=2min) {with sep(sample=s,program=centrifuge_program(drive=500g)) {}}')
    try:
        result = app.execute(plan, init_state(plan))
        assert result.ok, result.diagnostics
        assert len(fixture.port.processing) == 1
        assert fixture.port.processing[0].duration_seconds == 120
    finally:
        app.close()


def test_single_magnet_rejects_nested_retention_before_execution(tmp_path):
    source = DECLARATIONS + '''sample << [stock];
      with sep(sample=sample,program=magnetic_program(duration=2min)) {
        with sep(sample=sample,program=magnetic_program(duration=1min)) {
          waste << [sample.contents[1]:20uL];
        }
      }
    '''
    plan, _, app = MagneticFixture().build(tmp_path, source)
    try:
        result = app.execute(plan, init_state(plan))
        assert not result.ok
        assert 'PROCESSING_MAGNETIC_NESTED_SCOPE_UNSUPPORTED' in ' '.join(d.message for d in result.diagnostics)
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:
        app.close()


@pytest.mark.parametrize('transfer_limits,accepted', [
    ({'unit': 'C', 'minimum': 0, 'maximum': 10}, True),
    (None, False),
    ({'unit': 'C', 'minimum': 15, 'maximum': 30}, False),
])
def test_cold_separation_and_extraction_preserve_driver_conditions(tmp_path, monkeypatch, transfer_limits, accepted):
    from dataclasses import replace
    from tests.support.processing_engine.processing_centrifuge_separation import SeparationContractFixture, BASE, TRANSFER
    from culsma_os.device_manager.instruments.execution_models import EnvironmentCondition
    fixture = SeparationContractFixture(profile=None)
    original_build = fixture.build
    observed_transfers = []

    def build(context):
        port, snapshot, *rest = original_build(context)
        caps = {'centrifuge': {'rotor': {
            'labware': ['loaded'],
            'environment_conditions': {'thermal': {'unit': 'C', 'minimum': 0, 'maximum': 50}},
        }}}
        original_prepare = port.prepare

        def prepare_transfer(intent, bindings):
            observed_transfers.append(intent)
            assert intent.environment_conditions == (EnvironmentCondition('thermal', 4, 'C'),)
            assert intent.environment_targets == (intent.aliquots[0].source,)
            assert intent.target not in intent.environment_targets
            return original_prepare(intent, bindings)

        monkeypatch.setattr(port, 'prepare', prepare_transfer)
        monkeypatch.setattr(port, 'prepare_processing', lambda intent, bindings: intent)
        return port, replace(snapshot, processing_capabilities=caps,
            transfer_environment_conditions={'thermal': transfer_limits} if transfer_limits else {}), *rest

    monkeypatch.setattr(fixture, 'build', build)
    source = BASE + 'with env(thermal=4C,duration=2min) {with sep(sample=s,program=centrifuge_program(drive=500g)) {' + TRANSFER + '}}'
    plan, _, app = fixture.open(tmp_path, source)
    try:
        result = app.execute(plan, init_state(plan))
        assert result.ok is accepted, result.diagnostics
        if accepted:
            assert len(fixture.port.processing) == 1
            separation = fixture.port.processing[0]
            assert separation.duration_seconds == 120
            assert separation.environment_conditions == (EnvironmentCondition('thermal', 4, 'C'),)
            assert len(observed_transfers) == 1
            assert observed_transfers[0].producer_step_id == separation.step_id
            assert sorted(c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values()) == [10, 40]
        else:
            assert 'TRANSFER_ENVIRONMENT_CONDITION_UNSUPPORTED' in ' '.join(d.message for d in result.diagnostics)
            assert not fixture.port.executions
            assert not observed_transfers
    finally:
        app.close()


@pytest.mark.parametrize('body,expected', [
    ('with env(thermal=22C,duration=1min) {hold(sample=s);}', 'ThermalHoldIntent'),
    ('agit(sample=s,mode="shake",rate=200rpm,duration=5s);', 'OrbitalShakeIntent'),
    ('agit(sample=s,mode=AgitationMode.CENTRIFUGE,drive=300g,duration=5s);', 'CentrifugeIntent'),
])
def test_processing_inside_context_reaches_intent_validation(tmp_path, body, expected):
    """Scope metadata must not reject otherwise valid processing operations."""
    from culsma.driver.base import DriverResult
    from culsma.runtime.executor import run
    from culsma_os.driver_framework.adapters.semantic import SemanticReplayDriver
    from culsma_os.program_manager.interactors.replay import ReplayEffectInteractor
    from culsma_os.program_manager.interactors.processing_intents import ThermalHoldPreparationInteractor
    from culsma_os.program_manager.interactors.separation_intents import AgitationPreparationInteractor
    from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture
    from tests.support.processing_engine.processing_centrifuge_separation import BASE

    intents = []

    class IntentCollector(ReplayEffectInteractor):
        def execute(self, step):
            if step.op in {'env_hold', 'agit'}:
                pending = self.prepare_effect(step)
                assert pending.prepared.runtime_step.gate['separation_scopes']
                planner = ThermalHoldPreparationInteractor() if step.op == 'env_hold' else AgitationPreparationInteractor()
                intents.append(planner.resolve_intent(pending))
            return DriverResult(True, 'TEST_INTENT_PROJECTION', {})

    plan = TransferMatrixFixture().compile(BASE + 'with sep(sample=s,program=centrifuge_program(drive=500g)) {' + body + '}', tmp_path)
    state = init_state(plan)
    effects = IntentCollector({'plan': plan, 'scope_id': 'test-scope', 'confirmed': [], 'schema': 3}, state, None)
    result = run(plan, SemanticReplayDriver(effects), state)
    assert result.ok, result.diagnostics
    assert [type(intent).__name__ for intent in intents] == [expected]


@pytest.mark.parametrize('pellet_supported', [True, False])
def test_centrifuge_fraction_transfer_requires_its_own_driver_capability(tmp_path, monkeypatch, pellet_supported):
    from dataclasses import replace
    from culsma.driver.stub import StubDriver
    from culsma.runtime.executor import run
    from culsma_os.device_manager.instruments.pipetting.models import CentrifugePelletTransferIntent
    from tests.support.processing_engine.processing_centrifuge_separation import SeparationContractFixture, BASE

    fixture = SeparationContractFixture()
    original_build = fixture.build

    def build(context):
        port, snapshot, *rest = original_build(context)
        selections = ('centrifuge_supernatant', 'centrifuge_pellet') if pellet_supported else ('centrifuge_supernatant',)
        return port, replace(snapshot, transfer_selection_capabilities=selections), *rest

    monkeypatch.setattr(fixture, 'build', build)
    source = BASE + '''with sep(sample=s,program=centrifuge_program(drive=500g),
      component_fates={BUFFER:{supernatant:60%,pellet:40%}}) {
        d << [s.contents[0]];
        d << [s.contents[1]];
      }'''
    plan, _, app = fixture.open(tmp_path, source)
    try:
        result = app.execute(plan, init_state(plan))
        assert result.ok is pellet_supported, result.diagnostics
        if pellet_supported:
            assert len(fixture.port.processing) == 1
            upper, lower = fixture.port.transfers
            assert type(lower) is CentrifugePelletTransferIntent
            assert upper.selected_slot == '0' and lower.selected_slot == '1'
            assert upper.aliquots[0].volume_uL == 30 and lower.aliquots[0].volume_uL == 20
            assert upper.producer_step_id == lower.producer_step_id == fixture.port.processing[0].step_id
            assert result.state.artifacts['material_state'] == run(plan, StubDriver()).state.artifacts['material_state']
        else:
            assert 'DRIVER_TRANSFER_SELECTION_UNSUPPORTED' in ' '.join(d.message for d in result.diagnostics)
            assert not fixture.port.executions
    finally:
        app.close()
