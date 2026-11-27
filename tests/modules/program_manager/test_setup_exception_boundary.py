from types import SimpleNamespace
from unittest.mock import Mock
from culsma_os.program_manager.interactors.setup import RunSetupInteractor
from culsma_os.program_manager.interactors.resident import ResidentWorkerInteractor


def test_request_exception_is_reported_and_next_request_processed():
    setup = object.__new__(RunSetupInteractor)
    setup.snapshot = SimpleNamespace(setup_required=True)
    setup.repository = Mock()
    setup.repository.pending_requests.return_value = [
        {'request_id':str(n),'run_id':'run','action':'begin','fingerprint':'fp'} for n in (1,2)]
    setup.begin_loading = Mock(side_effect=[TypeError('broken'), {'phase':'loading'}])
    setup.process_requests()
    assert setup.repository.settle_request.call_count == 2
    first, second = setup.repository.settle_request.call_args_list
    assert 'broken' in first.kwargs['error']
    assert second.kwargs['result']['phase'] == 'loading'


def test_control_exception_is_not_a_worker_exit_or_false_success():
    worker = object.__new__(ResidentWorkerInteractor)
    worker.queue = Mock()
    worker.queue.pending_controls.return_value = [{'run_id':'run','action':'cancel','request_id':'cancel'}]
    worker.application = SimpleNamespace(client=Mock())
    worker.application.client.cancel_run.side_effect = RuntimeError('stop unconfirmed')
    worker.process_controls()
    worker.queue.settle_control.assert_called_once_with('cancel','stop unconfirmed')
