from dataclasses import replace
from pathlib import Path
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext, RunControlRequest, HostContractError
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.interactors.verification import CheckpointVerificationInteractor
from tests.support import FakeSessionFactory, ProgramFixture
import culsma_os.program_manager.interactors.semantics as semantics


class ChangedSessionFactory(FakeSessionFactory):
    def build(self, context):
        port, snapshot, positions, capacities, mapper = super().build(context)
        return port, replace(snapshot, configuration_revision="r2"), positions, capacities, mapper


class TestReviewBoundaries:
    @pytest.mark.parametrize('action', ['status', 'pause', 'cancel'])
    def test_control_never_loads_or_registers_device(self, tmp_path, action):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        app.client.lifecycle.runs.advance_ready(run_id)
        before = app.client.lifecycle.device.get('fake')
        def forbidden(*args):
            raise AssertionError('Control loaded an execution session')
        observer = OSApplicationFactory({'fake': ChangedSessionFactory()})
        observer.build = forbidden
        context = HostBuildContext(tmp_path/'os.sqlite3', 'missing-driver', tmp_path/'missing.json', tmp_path/'observer')
        try:
            result = observer.build_run_controller().execute(RunControlRequest(action, run_id, context))
            assert result['status'] == {'status':'waiting','pause':'paused','cancel':'cancel_requested'}[action]
            assert app.client.lifecycle.device.get('fake') == before
            assert factory.ports[0].executions == []
            if action == 'status':
                assert app.client.run_until_settled(run_id).status == 'completed'
            elif action == 'cancel':
                assert app.client.run_until_settled(run_id).status == 'cancelled'
        finally:
            app.close()

    def test_incompatible_resume_does_not_change_owner_or_catalog(self, tmp_path):
        app = FakeSessionFactory().open(tmp_path)
        app.client.start()
        run_id = app.client.submit_run(ProgramFixture.request())
        app.client.lifecycle.runs.advance_ready(run_id)
        app.client.pause_run(run_id)
        owner = app.client.lifecycle.reservations.get(run_id)
        before = app.client.lifecycle.device.get('fake')
        changed = ChangedSessionFactory()
        context = HostBuildContext(tmp_path/'os.sqlite3', 'fake', None, tmp_path/'observer')
        try:
            with pytest.raises(ValueError, match='DEVICE_SESSION_CONFIGURATION_MISMATCH'):
                OSApplicationFactory({'fake':changed}).build_run_controller().execute(RunControlRequest('resume',run_id,context))
            assert app.client.lifecycle.reservations.get(run_id) == owner
            assert app.client.lifecycle.device.get('fake') == before
            assert changed.ports[0].executions == []
        finally:
            app.close()

    def test_control_missing_database_never_creates_it(self, tmp_path):
        context = HostBuildContext(tmp_path/'absent.sqlite3', 'missing', None, tmp_path/'artifacts')
        with pytest.raises(ValueError, match='RUN_DATABASE_NOT_FOUND'):
            OSApplicationFactory().build_run_controller().execute(RunControlRequest('status','absent',context))
        assert not context.database_path.exists()

    def test_verified_checkpoint_cache_does_not_skip_changed_or_cold_inputs(self, monkeypatch):
        request = ProgramFixture.request()
        host = HostedRuntimeInteractor()
        checkpoint = host.advance(host.create(request.plan, request.state, 'review'))
        calls = []
        original = semantics.run
        def observe(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        monkeypatch.setattr(semantics, 'run', observe)
        decoded, _ = host.restore(checkpoint)
        assert len(calls) == 1
        decoded['state'].artifacts['mutated_returned_copy'] = True
        restored, _ = host.restore(checkpoint)
        assert len(calls) == 1
        assert 'mutated_returned_copy' not in restored['state'].artifacts
        cold = HostedRuntimeInteractor()
        cold.restore(checkpoint)
        assert len(calls) == 2
        damaged = host.codec.loads(checkpoint)
        damaged['pending'].prepared.driver_step.args['target'] = {'kind':'IRIdentifier','name':'wrong'}
        for _ in range(2):
            with pytest.raises(HostContractError, match='REPLAY_MISMATCH'):
                host.restore(host.codec.dumps(damaged))
        assert len(calls) == 4

    def test_verification_cache_is_bounded_and_does_not_survive_eviction(self):
        cache = CheckpointVerificationInteractor(2)
        cache.remember('one'); cache.remember('two')
        assert cache.is_verified('one')
        cache.remember('three')
        assert not cache.is_verified('two')
        assert cache.is_verified('one') and cache.is_verified('three')
        assert len(cache.verified) == 2

    def test_two_transfer_interpretation_count_is_bounded(self, tmp_path, monkeypatch):
        factory = FakeSessionFactory()
        app = factory.open(tmp_path)
        calls = []
        original = semantics.run
        def observe(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        monkeypatch.setattr(semantics, 'run', observe)
        try:
            request = ProgramFixture.request()
            assert app.execute(request.plan, request.state).ok
            assert len(factory.ports[0].executions) == 2
            assert len(calls) <= 5
        finally:
            app.close()

    def test_generic_registration_code_is_vendor_independent(self, tmp_path):
        app = FakeSessionFactory().open(tmp_path)
        try:
            request = ProgramFixture.request()
            result = app.execute(request.plan, request.state)
            assert result.ok
            codes = [event.payload.get('driver_code') for event in result.events]
            assert codes.count('OS_MATERIAL_REGISTERED') == 2
            assert 'DRV_OT_SIMULATED' not in codes
        finally:
            app.close()
