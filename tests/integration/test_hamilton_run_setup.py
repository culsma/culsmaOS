"""Operator preparation over the real Hamilton preparer, with no vendor/device execution."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.integration.hamilton import fixture, HamiltonOperationTestBackend


class SetupFixture:
    @staticmethod
    def app(context, backend=None):
        from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
        return OSApplicationFactory(session_factories={'hamilton-agent': HamiltonOSDeviceFactory(
            backend_factory=backend or HamiltonOperationTestBackend())}).build(context)

    @staticmethod
    def submit(app, compiled):
        app.client.start()
        run_id = app.client.submit_run(RunRequest(compiled.plan, compiled.state))
        return run_id, app.client.setup_plan(run_id)


def test_loading_plan_contains_materials_and_native_locations_and_requires_confirmation(fixture):
    compiled, context = fixture
    backend = HamiltonOperationTestBackend()
    app = SetupFixture.app(context, backend)
    try:
        run_id, plan = SetupFixture.submit(app, compiled)
        assert plan['preflight']['status'] == 'passed'
        assert app.client.get_run(run_id).status == 'awaiting_setup'
        assert len(plan['items']) == 2
        assert plan['items'][0]['initial_volume_uL'] == 200
        assert plan['items'][0]['initial_contents']['BUFFER']['value'] == 200
        assert all({'carrier','track','site'} <= set(row['placement']) for row in plan['items'])
        assert app.client.lifecycle.reservations.get(run_id) is None
        app.client.run_until_settled(run_id)
        app.client.resume_run(run_id)
        assert not backend.calls
        app.client.begin_setup(run_id, plan['fingerprint'])
        assert app.client.lifecycle.reservations.get(run_id).status == 'active'
        with pytest.raises(ValueError, match='SETUP_EXPLICIT_CONFIRMATION_REQUIRED'):
            app.client.confirm_setup(run_id, plan['fingerprint'])
        app.client.confirm_setup(run_id, plan['fingerprint'], True, 'simulation_fixture')
        app.client.run_until_settled(run_id)
        assert app.client.get_run(run_id).status == 'completed'
        assert len(backend.calls) == 2
        assert [p.start_tip_index for p,_ in backend.calls] == [0,1]
        assert not app.client.lifecycle.operations.resource.occupied()
    finally:
        app.close()


def test_begin_loading_excludes_other_programs_and_confirmation_cannot_be_skipped(fixture):
    compiled, context = fixture
    app = SetupFixture.app(context)
    try:
        first, plan1 = SetupFixture.submit(app, compiled)
        second, plan2 = SetupFixture.submit(app, compiled)
        app.client.begin_setup(first, plan1['fingerprint'])
        with pytest.raises(ValueError): app.client.begin_setup(second, plan2['fingerprint'])
        with pytest.raises(ValueError): app.client.confirm_setup(second, plan2['fingerprint'], True)
        app.client.run_until_settled(second)
        assert app.client.get_run(second).status == 'awaiting_setup'
    finally:
        app.close()


def test_revision_invalidates_confirmation_and_does_not_release_loading_reservation(fixture):
    compiled, context = fixture
    backend = HamiltonOperationTestBackend()
    app = SetupFixture.app(context, backend)
    try:
        run_id, plan = SetupFixture.submit(app, compiled)
        app.client.begin_setup(run_id, plan['fingerprint'])
        app.client.confirm_setup(run_id, plan['fingerprint'], True)
        allocation = plan['items'][0]['allocation_id']
        revised = app.client.revise_setup(run_id, {'fixed': {allocation: {'labware':'source_vessel','well':'1'}}})
        assert revised['fingerprint'] != plan['fingerprint']
        assert revised['confirmation'] is None and revised['phase'] == 'loading'
        assert app.client.lifecycle.reservations.get(run_id).status == 'active'
        with pytest.raises(ValueError, match='SETUP_PLAN_STALE'):
            app.client.confirm_setup(run_id, plan['fingerprint'], True)
        app.client.run_until_settled(run_id)
        assert not backend.calls
        app.client.confirm_setup(run_id, revised['fingerprint'], True, 'simulation_fixture')
        app.client.run_until_settled(run_id)
        assert len(backend.calls) == 2
        assert backend.calls[0][0].report['bindings'][0]['labware'] == 'source_vessel'
    finally:
        app.close()


@pytest.mark.parametrize('confirmed', [False, True])
def test_restart_preserves_loading_gate_and_matching_confirmation(fixture, confirmed):
    compiled, context = fixture
    app = SetupFixture.app(context)
    run_id, plan = SetupFixture.submit(app, compiled)
    app.client.begin_setup(run_id, plan['fingerprint'])
    if confirmed: app.client.confirm_setup(run_id, plan['fingerprint'], True, 'simulation_fixture')
    app.close()
    backend = HamiltonOperationTestBackend()
    restarted = SetupFixture.app(context, backend)
    try:
        restarted.client.take_over_run(run_id)
        restarted.client.start()
        restarted.client.run_until_settled(run_id)
        assert len(backend.calls) == (2 if confirmed else 0)
        assert restarted.client.get_run(run_id).status == ('completed' if confirmed else 'awaiting_setup')
    finally:
        restarted.close()


def test_configuration_change_rejects_old_confirmation(fixture):
    compiled, context = fixture
    app = SetupFixture.app(context)
    run_id, plan = SetupFixture.submit(app, compiled)
    app.close()
    raw = json.loads(context.config_path.read_text())
    raw['execution']['liquid_class'] = 'changed'
    context.config_path.write_text(json.dumps(raw))
    app = SetupFixture.app(context)
    try:
        with pytest.raises(ValueError, match='SETUP_PLAN_STALE'):
            app.client.begin_setup(run_id, plan['fingerprint'])
    finally:
        app.close()


def test_confirmation_and_cancellation_are_idempotent_before_any_device_action(fixture):
    compiled, context = fixture
    app = SetupFixture.app(context)
    try:
        run_id, plan = SetupFixture.submit(app, compiled)
        app.client.begin_setup(run_id, plan['fingerprint'])
        first = app.client.confirm_setup(run_id, plan['fingerprint'], True)
        assert app.client.confirm_setup(run_id, plan['fingerprint'], True) == first
        app.client.cancel_run(run_id)
        assert app.client.get_run(run_id).status == 'cancelled'
        assert app.client.lifecycle.reservations.get(run_id).status == 'released'
    finally:
        app.close()


def test_plate_group_is_automatically_bound_as_one_physical_plate(fixture):
    _, context = fixture
    from culsma_os.program_manager.interactors.compilation import CompilationInteractor
    raw = json.loads(context.config_path.read_text())
    raw['bindings'] = {}
    raw['well_positions'] = {'destination_plate': {'A1':'1', 'B1':'2'}}
    context.config_path.write_text(json.dumps(raw))
    source = context.config_path.parent/'plate.culs'
    source.write_text('let source=tube(capacity=2000uL,load=[content(kind=formulation,type=buffer,code="BUFFER"):200uL]);'
        'let p=plate(format="96well",capacity=2000uL); let w=p[A1:B1];'
        'w[0] << [source:50uL]; w[1] << [source:50uL];')
    compiled = CompilationInteractor().compile([source])
    backend = HamiltonOperationTestBackend()
    app = SetupFixture.app(context, backend)
    try:
        run_id, plan = SetupFixture.submit(app, compiled)
        wells = [row for row in plan['items'] if row['kind']=='well']
        assert len(plan['loadout'])==2
        plate_load = next(row for row in plan['loadout'] if row['labware']=='destination_plate')
        assert len(plate_load['containers'])==2
        assert len(wells)==2
        assert {row['address']['labware'] for row in wells}=={'destination_plate'}
        assert {row['address']['well'] for row in wells}=={'A1','B1'}
        source_row = next(row for row in plan['items'] if row['kind']=='tube')
        assert source_row['address']['labware']=='source_vessel'
        app.client.begin_setup(run_id, plan['fingerprint'])
        app.client.confirm_setup(run_id, plan['fingerprint'], True, 'simulation_fixture')
        app.client.run_until_settled(run_id)
        assert app.client.get_run(run_id).status=='completed'
        assert len(backend.calls)==2
        assert [next(b['position'] for b in p.report['bindings'] if b['container_id']==p.intent.target.container_id) for p,_ in backend.calls]==['1','2']
    finally:
        app.close()


def test_local_cli_show_begin_confirm_and_resume_use_the_same_saved_plan(fixture, monkeypatch, capsys):
    compiled, context = fixture
    backend = HamiltonOperationTestBackend()
    from culsma_hamilton_os.providers import HamiltonAgentBackendFactory
    from culsma_os.cli import CulsmaOSCLI
    monkeypatch.setattr(HamiltonAgentBackendFactory, 'build', lambda self, configuration: backend)
    app = SetupFixture.app(context)
    run_id, plan = SetupFixture.submit(app, compiled)
    app.close()
    common = [run_id, '--host-db', str(context.database_path), '--driver', 'hamilton-agent',
              '--driver-config', str(context.config_path)]
    for action in ['show','begin','confirm']:
        args = ['setup', *common, '--action', action]
        if action != 'show': args += ['--fingerprint', plan['fingerprint']]
        if action == 'confirm': args += ['--acknowledge']
        with pytest.raises(SystemExit) as result: CulsmaOSCLI.main(args)
        assert result.value.code == 0
        response = json.loads(capsys.readouterr().out)
        assert response['fingerprint'] == plan['fingerprint']
        assert not backend.calls
    with pytest.raises(SystemExit) as result: CulsmaOSCLI.main(['resume', *common])
    assert result.value.code == 0
    response = json.loads(capsys.readouterr().out)
    assert response['status']=='completed' and len(backend.calls)==2


def test_dispatch_guard_rejects_a_confirmation_removed_after_runtime_preparation(fixture):
    compiled, context = fixture
    backend = HamiltonOperationTestBackend()
    app = SetupFixture.app(context, backend)
    try:
        run_id, plan = SetupFixture.submit(app, compiled)
        app.client.begin_setup(run_id, plan['fingerprint'])
        app.client.confirm_setup(run_id, plan['fingerprint'], True, 'simulation_fixture')
        # Reach the first hardware boundary without invoking the operation scheduler.
        app.client.lifecycle.runs.advance_ready(run_id)
        assert app.client.get_run(run_id).status=='waiting'
        setup = app.client.tasks.setup
        record = setup.get(run_id)
        record.update(phase='loading', confirmation=None)
        setup.repository.save(run_id, record, record['revision'])
        app.client.lifecycle.operations.dispatch_ready(run_id)
        assert not backend.calls
        assert app.client.get_run(run_id).status=='needs_reconciliation'
    finally:
        app.close()


def test_resident_submission_waits_for_the_same_operator_setup_and_durable_commands(fixture):
    from culsma_os.lifecycle_manager.models import ResidentHostSettings
    from tests.support.integration.resident_host import ResidentHarness
    from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
    _, context = fixture
    backend = HamiltonOperationTestBackend()
    class HamiltonHarness(ResidentHarness):
        def serve(self):
            try:
                applications = OSApplicationFactory({'hamilton-agent': HamiltonOSDeviceFactory(backend_factory=backend)})
                self.host = applications.build_resident_host(self.settings)
                self.host.serve()
            except BaseException as error:
                self.errors.append(error)
    harness = HamiltonHarness(context.database_path.parent)
    harness.context = context
    harness.settings = ResidentHostSettings(context, harness.endpoint, 0.01)
    try:
        harness.start()
        receipt = harness.client.execute({'action':'submit','source':str(context.config_path.parent/'transfer.culs')})
        run_id = receipt['run_id']
        harness.wait(lambda: harness.status(run_id)['status']=='awaiting_setup')
        plan = harness.client.execute({'action':'setup-show','run_id':run_id})
        assert not backend.calls
        for action in ['begin','confirm']:
            request_id = 'test-setup-'+action
            payload = {'action':'setup-'+action,'run_id':run_id,'request_id':request_id,
                       'setup_fingerprint':plan['fingerprint'],'setup_acknowledged':action=='confirm'}
            harness.client.execute(payload)
            status = {'action':'setup-status','run_id':run_id,'request_id':request_id}
            harness.wait(lambda: harness.client.execute(status)['status']!='pending')
            completed = harness.client.execute(status)
            assert completed['status']=='completed', completed
            assert harness.client.execute(payload)['status']=='completed'
            if action=='begin':
                assert not backend.calls
                assert harness.status(run_id)['status']=='awaiting_setup'
        harness.wait(lambda: harness.status(run_id)['status']=='completed')
        assert len(backend.calls)==2
    finally:
        harness.stop()
