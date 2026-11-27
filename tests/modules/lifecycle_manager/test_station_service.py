import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from culsma_os.lifecycle_manager.station_service import StationServiceRepository, StationServiceInteractor
from culsma_os.program_manager.adapters.resident import ResidentProtocolAdapter
from culsma_os.program_manager.interactors.resident import ResidentCommandInteractor

@pytest.fixture
def fixture(tmp_path):
    db=tmp_path/'services.db'
    connection=sqlite3.connect(db)
    port=Mock()
    port.submit.return_value={'state':'accepted'}
    port.inspect.return_value={'state':'completed'}
    configuration=SimpleNamespace(fingerprint='configuration-one')
    service=StationServiceInteractor(StationServiceRepository(connection),port,configuration)
    request={'action':'initialize','request_id':'one','method_id':'initialize','bundle_sha256':'digest','acknowledge_clearance':True}
    return db,service,port,request,Mock()

def test_duplicate_after_restart_observes_original_job(fixture):
    db,service,port,request,idle=fixture
    assert service.execute(request,idle)['state']=='accepted'
    service=StationServiceInteractor(StationServiceRepository(sqlite3.connect(db)),port,service.configuration)
    assert service.execute(request,idle)['state']=='completed'
    assert service.execute(request,idle)['state']=='completed'
    assert port.submit.call_count==1 and port.inspect.call_count==1
    service.require_settled()

def test_disconnect_persists_unknown_and_never_resubmits(fixture):
    _,service,port,request,idle=fixture
    def lost(*args):
        assert service.repository.get('one')[1]=='pending'
        raise ConnectionError('lost after possible dispatch')
    port.submit.side_effect=lost
    port.inspect.side_effect=ConnectionError('still disconnected')
    assert service.execute(request,idle)['state']=='unknown'
    assert service.execute(request,idle)['state']=='unknown'
    with pytest.raises(ValueError,match='UNRESOLVED'): service.require_settled()
    with pytest.raises(ValueError,match='UNRESOLVED'): service.execute({**request,'request_id':'two'},idle)
    assert port.submit.call_count==1

@pytest.mark.parametrize('change',['clearance','busy','method'])
def test_rejection_before_dispatch(fixture,change):
    _,service,port,request,idle=fixture
    if change=='clearance': request['acknowledge_clearance']=False
    if change=='busy': idle.side_effect=ValueError('HOST_CONFIGURATION_BUSY')
    if change=='method': port.validate.side_effect=ValueError('METHOD_MISMATCH')
    with pytest.raises(ValueError): service.execute(request,idle)
    assert not port.submit.called and service.repository.unsettled() is None

def test_identity_or_configuration_change_cannot_reuse_pending_action(fixture):
    _,service,port,request,idle=fixture
    service.execute(request,idle)
    with pytest.raises(ValueError,match='ID_CONFLICT'): service.execute({**request,'method_id':'other'},idle)
    service.configuration.fingerprint='changed'
    with pytest.raises(ValueError,match='CONFIGURATION_CHANGED'): service.execute({'action':'status','request_id':'one'},idle)
    assert not port.inspect.called and port.submit.call_count==1

@pytest.mark.parametrize('action',['submit','start','resume'])
def test_unresolved_service_gates_experiment_entry(fixture,action):
    _,service,port,request,idle=fixture
    service.execute(request,idle)
    commands=ResidentCommandInteractor(*[Mock() for _ in range(10)],station_service=service)
    with pytest.raises(ValueError,match='UNRESOLVED'):
        commands.execute(ResidentProtocolAdapter.request({'action':action,'run_id':'experiment'}))
    with pytest.raises(ValueError,match='UNRESOLVED'): commands.require_idle_configuration()

def test_protocol_preserves_service_request_and_rejects_wrong_shape():
    payload={'action':'station-service','station_service_request':{'action':'describe'}}
    assert ResidentProtocolAdapter.request(payload).station_service_request==payload['station_service_request']
    with pytest.raises(ValueError): ResidentProtocolAdapter.request({**payload,'station_service_request':[]})


def test_cancel_releases_service_and_retains_history_after_restart(fixture):
    db, service, port, request, idle = fixture
    service.execute(request, idle)
    port.cancel.return_value = {'state': 'cancelled', 'diagnostic': 'OPERATOR_CANCELLED'}
    result = service.execute({'action': 'cancel', 'request_id': 'one'}, idle)
    assert result['state'] == 'cancelled'
    service.require_settled()
    port.cancel.assert_called_once()
    assert idle.call_count == 1  # Cancellation cannot require the station to be released first.
    service = StationServiceInteractor(StationServiceRepository(sqlite3.connect(db)), port, service.configuration)
    for action in ('status', 'cancel', 'initialize'):
        assert service.execute({**request, 'action': action}, idle) == result
    port.cancel.assert_called_once()
    assert service.repository.get('one')[1] == 'cancelled'
    assert service.execute({**request, 'request_id': 'two'}, idle)['state'] == 'accepted'


def test_cancel_failure_retains_blocker_and_lost_reply_can_be_reconciled(fixture):
    _, service, port, request, idle = fixture
    service.execute(request, idle)
    port.cancel.side_effect = ConnectionError('lost cancel reply')
    with pytest.raises(ConnectionError):
        service.execute({'action': 'cancel', 'request_id': 'one'}, idle)
    with pytest.raises(ValueError, match='UNRESOLVED'):
        service.require_settled()
    port.inspect.return_value = {'state': 'cancelled'}
    assert service.execute({'action': 'status', 'request_id': 'one'}, idle)['state'] == 'cancelled'
    service.require_settled()


def test_late_status_does_not_overwrite_cancelled_record(fixture):
    _, service, port, request, idle = fixture
    service.execute(request, idle)
    service.repository.settle('one', {'state': 'cancelled', 'diagnostic': 'OPERATOR_CANCELLED'})
    assert service.repository.settle('one', {'state': 'running'})['state'] == 'cancelled'
    service.require_settled()


def test_cancel_missing_or_unsupported_service_does_not_create_task(fixture):
    _, service, port, request, idle = fixture
    with pytest.raises(ValueError, match='NOT_FOUND'):
        service.execute({'action': 'cancel', 'request_id': 'missing'}, idle)
    service.execute(request, idle)
    port.cancel = None
    with pytest.raises(ValueError, match='CANCELLATION_UNSUPPORTED'):
        service.execute({'action': 'cancel', 'request_id': 'one'}, idle)
    assert service.repository.unsettled()


def test_run_logs_resolves_owned_attempt_without_admission_or_dispatch(fixture):
    _, service, port, _, idle = fixture
    service.run_evidence = Mock(return_value={'attempts': [{'attempt_id':'attempt', 'mode':'physical',
        'context': {'description': {'entrypoint':'batch.hsl'}}}]})
    port.operation_logs.return_value = {'content':'eA==','offset':0,'next_offset':1,'encoding':'base64'}
    request = {'action':'run-logs','run_id':'run','attempt_id':'attempt','stream':'trace'}
    result = service.execute(request, idle)
    assert result['run_id'] == 'run' and result['attempt_id'] == 'attempt'
    port.operation_logs.assert_called_once_with('attempt','physical',{'entrypoint':'batch.hsl'},0,65536,'trace')
    idle.assert_not_called(); port.submit.assert_not_called()
    with pytest.raises(ValueError, match='ATTEMPT_NOT_FOUND'):
        service.execute({**request,'attempt_id':'foreign'}, idle)
    with pytest.raises(ValueError, match='CURSOR_INVALID'):
        service.execute({**request,'limit':True}, idle)
    assert port.operation_logs.call_count == 1
