import pytest

from culsma_os.program_manager.interactors.console import ConsoleCommandInteractor
from culsma_os.program_manager.models import ConsoleReadError, ConsoleReadRequest
from tests.support.console.http import ResidentReadFixture


class TestConsoleCommand:
    def test_station_reads_existing_owners_without_advancing(self):
        resident = ResidentReadFixture()
        resident.responses['host-status'].update(blocked_run='run-1', blocked_reason='unknown')
        resident.responses['device-status']['devices'] = [{'device_id': 'sim',
            'consumables': {'tips': {'available_from_records': None}}}]
        response = ConsoleCommandInteractor(resident).execute(ConsoleReadRequest('station')).as_dict()
        assert resident.calls == [{'action': 'host-status'}, {'action': 'device-status'}, {'action': 'runs'}]
        assert response['schema'] == 'culsma_console_v1'
        assert response['consistency'] == 'independent_resident_reads'
        assert response['observed_at'] and response['source'] == 'resident_service'
        assert response['data']['devices']['hardware_observed'] is False
        assert response['data']['host']['blocked_reason'] == 'unknown'
        assert response['data']['devices']['devices'][0]['consumables']['tips']['available_from_records'] is None

    @pytest.mark.parametrize('resource', ['submit', 'pause', 'resume', 'cancel', 'shutdown', 'advance'])
    def test_mutation_resources_never_reach_resident(self, resource):
        resident = ResidentReadFixture()
        interactor = ConsoleCommandInteractor(resident)
        for call in (lambda: interactor.execute(ConsoleReadRequest(resource)),
                     lambda: interactor.read({'action': resource})):
            with pytest.raises(ConsoleReadError, match='CONSOLE_READ_ONLY'):
                call()
        assert resident.calls == []

    @pytest.mark.parametrize('run_id', [None, '', '../run', 'a/b', 'a\nb', 'x' * 129, 7, '\u8fd0\u884c'])
    def test_invalid_run_identifiers_never_reach_resident(self, run_id):
        resident = ResidentReadFixture()
        with pytest.raises(ConsoleReadError, match='CONSOLE_RUN_ID_INVALID'):
            ConsoleCommandInteractor(resident).execute(ConsoleReadRequest('run', run_id))
        assert resident.calls == []

    def test_run_detail_uses_existing_inspection_and_preserves_result(self):
        resident = ResidentReadFixture()
        resident.responses['status']['result'] = {'os': {'registered_material': {'version': 3}}}
        response = ConsoleCommandInteractor(resident).execute(ConsoleReadRequest('run', 'run-1'))
        assert resident.calls == [{'action': 'status', 'run_id': 'run-1'}, {'action': 'run-evidence', 'run_id': 'run-1'}]
        assert response.data['result']['os']['registered_material']['version'] == 3

    @pytest.mark.parametrize('failure,code,kind', [
        (FileNotFoundError('/private/socket'), 'CONSOLE_HOST_UNAVAILABLE', 'unavailable'),
        (TimeoutError('no response'), 'CONSOLE_HOST_UNAVAILABLE', 'unavailable'),
        (ValueError('HOST_RUN_NOT_FOUND'), 'HOST_RUN_NOT_FOUND', 'not_found'),
        (ValueError('private runtime error /secret/path'), 'CONSOLE_BACKEND_REJECTED', 'bad_response'),
    ])
    def test_read_failures_have_stable_codes_without_private_error_text(self, failure, code, kind):
        resident = ResidentReadFixture(); resident.failure = failure
        with pytest.raises(ConsoleReadError) as error:
            ConsoleCommandInteractor(resident).execute(ConsoleReadRequest('runs'))
        assert error.value.code == code and error.value.kind == kind
        assert '/private' not in str(error.value) and '/secret' not in str(error.value)

    def test_malformed_backend_does_not_become_an_empty_successful_queue(self):
        resident = ResidentReadFixture(); resident.responses['runs'] = {'runs': None}
        with pytest.raises(ConsoleReadError, match='CONSOLE_BACKEND_RESPONSE_INVALID'):
            ConsoleCommandInteractor(resident).execute(ConsoleReadRequest('runs'))


    def test_existing_service_without_evidence_query_keeps_its_run_report(self):
        class ExistingResident(ResidentReadFixture):
            def execute(self, payload):
                if payload['action'] == 'run-evidence':
                    raise ValueError('HOST_COMMAND_UNSUPPORTED')
                return super().execute(payload)
        result = ConsoleCommandInteractor(ExistingResident()).execute(ConsoleReadRequest('run','run-1'))
        assert result.data['status'] == 'completed' and result.data['execution_evidence'] is None
