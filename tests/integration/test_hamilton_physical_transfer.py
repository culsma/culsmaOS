"""Physical-mode OS accounting with an explicit test double, no hardware IO."""
import json
import pytest
from tests.support.integration.hamilton import fixture, HamiltonOperationTestBackend
from tests.support.integration.hamilton_setup import SetupFixture


@pytest.mark.parametrize('strategy', ['stepwise', 'batch'])
@pytest.mark.parametrize('outcome', ['completed', 'unknown', 'rejected'])
def test_hardware_mode_keeps_loading_gate_and_registers_only_confirmed_results(fixture, strategy, outcome):
    compiled, context = fixture
    config = json.loads(context.config_path.read_text())
    config.update(mode='physical', execution_strategy=strategy)
    context.config_path.write_text(json.dumps(config))
    backend = HamiltonOperationTestBackend(outcome)
    app = SetupFixture.app(context, backend)
    try:
        run_id, plan = SetupFixture.submit(app, compiled)
        app.client.run_until_settled(run_id)
        assert not backend.calls
        assert app.client.get_run(run_id).status == 'awaiting_setup'
        app.client.begin_setup(run_id, plan['fingerprint'])
        with pytest.raises(ValueError):
            app.client.confirm_setup(run_id, plan['fingerprint'], True, 'simulation_fixture')
        assert not backend.calls
        app.client.confirm_setup(run_id, plan['fingerprint'], True, 'operator_attestation')
        result = app.client.run_until_settled(run_id)
        assert result.status == {'completed': 'completed', 'unknown': 'needs_reconciliation', 'rejected': 'failed'}[outcome], result
        assert backend.calls and all(p.mode == 'physical' for p, _ in backend.calls)
        ops = app.client.lifecycle.operations
        if outcome == 'completed':
            assert ops.material.get(run_id)[0] == 'physical'
            assert ops.material.get(run_id)[2] == 2
            assert not ops.resource.occupied()
            assert app.client.lifecycle.reservations.get(run_id).status == 'released'
            assert ops.evidence.known_consumption(config['device_id'], mode='physical')
            assert ops.evidence.known_consumption(config['device_id'], mode='simulation') == {}
        else:
            assert ops.material.get(run_id)[2] == 0
            if outcome == 'unknown': assert ops.resource.occupied()
        calls = len(backend.calls)
        app.client.run_until_settled(run_id)
        assert len(backend.calls) == calls
    finally:
        app.close()


def test_completed_physical_run_restarts_without_replay_and_keeps_tip_usage(fixture):
    compiled, context = fixture
    config = json.loads(context.config_path.read_text())
    config.update(mode='physical', execution_strategy='batch')
    context.config_path.write_text(json.dumps(config))
    backend = HamiltonOperationTestBackend()
    app = SetupFixture.app(context, backend)
    try:
        run_id, plan = SetupFixture.submit(app, compiled)
        app.client.begin_setup(run_id, plan['fingerprint'])
        app.client.confirm_setup(run_id, plan['fingerprint'], True, 'operator_attestation')
        assert app.client.run_until_settled(run_id).status == 'completed'
        count = len(backend.calls)
    finally:
        app.close()
    restarted = SetupFixture.app(context, backend)
    try:
        restarted.client.start()
        assert restarted.client.run_until_settled(run_id).status == 'completed'
        assert len(backend.calls) == count
        assert restarted.client.lifecycle.reservations.released_safely(run_id)
        evidence = restarted.client.lifecycle.operations.evidence
        assert sum(evidence.known_consumption(config['device_id'], mode='physical').values()) == 2
        assert evidence.known_consumption(config['device_id']) == {}
    finally:
        restarted.close()
