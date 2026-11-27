"""Preparation exceptions must leave cancellation and the resident available."""
from pathlib import Path
import culsma_driver_hamilton
import pytest
from culsma_os.program_manager.interactors.setup import RunSetupInteractor
from tests.support.integration.shared_setup import SharedSetupHarness


@pytest.mark.parametrize('stage', ['plan', 'automatic', 'revise'])
def test_unexpected_setup_exception_can_be_cancelled_and_next_run_prepared(tmp_path, monkeypatch, stage):
    driver = Path(culsma_driver_hamilton.__file__).resolve().parents[2]
    monkeypatch.setenv('CULSMA_HAMILTON_PRIVATE_LABWARE', str(driver / 'reference/LabWare'))
    with SharedSetupHarness(tmp_path, submit=False) as harness:
        original = RunSetupInteractor.plan
        def broken_plan(self, *args, **kwargs):
            raise TypeError('injected declaration projection failure')
        if stage in {'plan', 'automatic'}:
            monkeypatch.setattr(RunSetupInteractor, 'plan', broken_plan)
        run_id = harness.client.execute({'action': 'start' if stage == 'automatic' else 'prepare', 'source': str(harness.source)})['run_id']
        if stage == 'revise':
            harness.wait(lambda: harness.client.execute({'action':'setup-show','run_id':run_id}).get('fingerprint'))
            plan = harness.client.execute({'action':'setup-show','run_id':run_id})
            harness.client.execute({'action':'setup-begin','run_id':run_id,'setup_fingerprint':plan['fingerprint'],'request_id':'begin'})
            harness.wait(lambda: harness.client.execute({'action':'setup-status','run_id':run_id,'request_id':'begin'})['status'] != 'pending')
            monkeypatch.setattr(RunSetupInteractor, 'plan', broken_plan)
            harness.client.execute({'action':'setup-revise','run_id':run_id,'request_id':'broken-revision'})
            result = harness.wait(lambda: (r if (r := harness.client.execute({'action':'setup-status','run_id':run_id,'request_id':'broken-revision'}))['status'] != 'pending' else None))
            assert 'injected declaration' in result['error']
        elif stage == 'automatic':
            harness.wait(lambda: harness.status(run_id)['status'] == 'failed')
        else:
            harness.wait(lambda: harness.client.execute({'action':'host-status'}).get('blocked_reason'))
        assert harness.client.execute({'action':'host-status'})['status'] == 'ready'
        harness.client.execute({'action':'cancel','run_id':run_id,'request_id':'cancel'})
        harness.wait(lambda: harness.status(run_id)['status'] == ('failed' if stage == 'automatic' else 'cancelled'))
        assert not harness.backend.calls
        monkeypatch.setattr(RunSetupInteractor, 'plan', original)
        next_id = harness.client.execute({'action':'prepare','source':str(harness.source)})['run_id']
        next_plan = harness.wait(lambda: (r if (r := harness.client.execute({'action':'setup-show','run_id':next_id})).get('fingerprint') else None))
        harness.client.execute({'action':'setup-begin','run_id':next_id,'setup_fingerprint':next_plan['fingerprint'],'request_id':'next-begin'})
        outcome = harness.wait(lambda: (r if (r := harness.client.execute({'action':'setup-status','run_id':next_id,'request_id':'next-begin'}))['status'] != 'pending' else None))
        assert not outcome.get('error')  # The preceding run really released the station.
        harness.client.execute({'action':'cancel','run_id':next_id})
        harness.wait(lambda: harness.status(next_id)['status'] == 'cancelled')
