from copy import deepcopy
from unittest.mock import Mock
import pytest

from tests.support.common import FakeSessionFactory, ProgramFixture


def stopped(attempt_id, mode, description):
    return {'attempt_id': attempt_id, 'mode': mode, 'state': 'stopped', 'evidence_ref': 'original-agent-job'}


def interrupted(tmp_path):
    factory = FakeSessionFactory()
    app = factory.open(tmp_path)
    app.client.start()
    run_id = app.client.submit_run(ProgramFixture.request())
    port = app.host.gateway.port
    original = port.execute
    def unknown(plan, attempt_id):
        value = original(plan, attempt_id)
        return {**value, 'outcome': 'unknown', 'consumed_resources': {}}
    port.execute = unknown
    record = app.client.run_until_settled(run_id)
    assert record.status == 'needs_reconciliation'
    port.cancel_attempt = Mock(side_effect=stopped)
    return factory, app, run_id


def test_cancel_unknown_releases_both_os_reservations_without_inventing_result(tmp_path):
    _, app, run_id = interrupted(tmp_path)
    try:
        lifecycle = app.client.lifecycle
        attempt = lifecycle.evidence.attempts_for_run(run_id)[0]
        before = deepcopy(lifecycle.evidence.find_evidence(attempt.effect_id))
        uncertainty = app.host.material.uncertainties(run_id)
        calls = list(app.host.gateway.port.executions)
        assert app.client.cancel_run(run_id).status == 'cancelled'
        assert lifecycle.reservations.get(run_id).status == 'released'
        assert lifecycle.operations.resource.occupied() == ()
        assert lifecycle.operations.resource.active_attempts() == ()
        assert lifecycle.evidence.find_evidence(attempt.effect_id) == before
        assert app.host.material.uncertainties(run_id) == uncertainty
        assert not app.client.result(run_id).ok
        assert lifecycle.evidence.known_consumption(attempt.context['device_id']) == {'tips': 1}
        assert app.client.cancel_run(run_id).status == 'cancelled'
        app.host.gateway.port.cancel_attempt.assert_called_once()
        assert app.host.gateway.port.executions == calls
        from culsma_os.bootstrap import OSApplicationFactory
        from culsma_os.program_manager.models import HostBuildContext
        inspector = OSApplicationFactory().build_device_inspector(HostBuildContext(
            tmp_path / 'os.sqlite3', 'fake', None, tmp_path / 'inspection'))
        observed = inspector.execute()
        assert observed['devices'][0]['unresolved_operations'] == []
        assert observed['resources']['station_reservations'] == []
        assert observed['devices'][0]['consumables']['tips']['available_from_records'] == 95
        assert observed['devices'][0]['consumables']['tips']['known_consumed'] == 0
        assert observed['devices'][0]['consumables']['tips']['unconfirmed_reserved'] == 1
        next_run = app.client.submit_run(ProgramFixture.request())
        lifecycle.runs.advance_ready(next_run)
        assert lifecycle.reservations.get(next_run).status == 'active'
    finally:
        app.close()


@pytest.mark.parametrize('reason', ['VENUS_NOT_IDLE', 'reply lost', 'DEVICE_CANCELLATION_UNSUPPORTED'])
def test_unconfirmed_cancel_keeps_ownership_then_retries_original_attempt(tmp_path, reason):
    _, app, run_id = interrupted(tmp_path)
    try:
        port = app.host.gateway.port
        port.cancel_attempt.side_effect = ValueError(reason)
        result = app.client.cancel_run(run_id)
        assert result.status == 'needs_reconciliation' and reason in result.error
        assert app.client.lifecycle.reservations.get(run_id).status == 'active'
        first = port.cancel_attempt.call_args
        port.cancel_attempt.side_effect = stopped
        assert app.client.advance_run(run_id).status == 'cancelled'
        assert port.cancel_attempt.call_args == first
        assert len(port.executions) == 1
    finally:
        app.close()


def test_restart_keeps_original_stop_and_never_redispatches(tmp_path):
    factory, app, run_id = interrupted(tmp_path)
    finalizer = app.client.lifecycle.finalization
    finalizer.state.complete_finalization = Mock(side_effect=KeyboardInterrupt('after release'))
    with pytest.raises(KeyboardInterrupt):
        app.client.cancel_run(run_id)
    app.close()
    restarted = factory.open(tmp_path)
    try:
        restarted.host.gateway.port.cancel_attempt = Mock(side_effect=AssertionError('must use persisted stop'))
        restarted.client.start()
        assert restarted.client.get_run(run_id).status == 'cancelled'
        assert restarted.host.gateway.port.executions == []
        assert restarted.client.lifecycle.reservations.get(run_id).status == 'released'
    finally:
        restarted.close()


def test_venus_cancellation_releases_the_os_and_driver_reservation(tmp_path):
    from hashlib import sha256
    from types import SimpleNamespace

    station_module = pytest.importorskip('culsma_driver_hamilton.venus.station')
    from culsma_driver_hamilton.models import MethodArtifact
    from culsma_hamilton_os.providers import HamiltonVenusTransferInteractor

    api = Mock()
    api.exchange.return_value = 0
    station = station_module.VenusStation(tmp_path / 'venus', {
        'schema': 'culsma_hamilton_venus_v1', 'allow_physical_execution': False,
        'allow_venus_simulation': True, 'methods': [],
        'venus': {'port': 1, 'trace_directory': str(tmp_path / 'traces')},
    }, api)
    client = station_module.VenusStationClient(station, 'simulation')
    backend = HamiltonVenusTransferInteractor(client, generated_methods=station.generated_methods)
    prepared = SimpleNamespace(mode='simulation', report={'entrypoint': 'transfer.hsl'},
        artifacts=tuple(MethodArtifact(name, 'application/octet-stream', content, sha256(content).hexdigest())
            for name, content in {'transfer.hsl': b'fake method', 'transfer.stp': b'fake steps'}.items()))
    method_id, _ = backend.identity(prepared)
    station.generated_methods.publish(method_id, 'simulation', 'transfer.hsl', prepared.artifacts)
    app = FakeSessionFactory().open(tmp_path / 'os')
    try:
        app.client.start()
        port = app.host.gateway.port
        describe, execute = port.describe, port.execute
        port.describe = lambda plan: {**describe(plan), 'entrypoint': 'transfer.hsl',
            'artifact_hashes': {a.name: a.sha256 for a in prepared.artifacts}}
        requests = []

        def uncertain(plan, attempt_id):
            request = backend.request(prepared, attempt_id)
            requests.append(request)
            station.admit.execute(request)
            station.jobs.claim(request.job_id)
            return {**execute(plan, attempt_id), 'outcome': 'unknown', 'consumed_resources': {}}

        port.execute = uncertain
        port.cancel_attempt = backend.cancel_attempt
        run_id = app.client.submit_run(ProgramFixture.request())
        assert app.client.run_until_settled(run_id).status == 'needs_reconciliation'
        assert client.station()['state'] == 'busy'
        assert app.client.cancel_run(run_id).status == 'cancelled'
        assert client.station()['state'] == 'ready'
        assert client.inspect(requests[0])['state'] == 'cancelled'
        assert app.client.lifecycle.reservations.get(run_id).status == 'released'
        assert not app.client.lifecycle.operations.resource.active_attempts()
        assert not app.client.lifecycle.operations.resource.occupied()
        assert len(requests) == 1
        api.exchange.assert_called_once_with(1, 'GET', 'run-state')
    finally:
        app.close()
