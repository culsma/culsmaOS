"""Edit driver-declared parameters in a detached, revision-bound station draft."""
import hashlib
import json
import re
from uuid import uuid4

from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.workspace_manager.models import ConfigurationError


def instrument_identity(device_id, module_id):
    return json.dumps([device_id, module_id], separators=(',', ':'))


def valid_request(value):
    if not isinstance(value, dict):
        return False
    keys = {'action', 'configuration_fingerprint'}
    if not isinstance(value.get('configuration_fingerprint'), str) or not re.fullmatch(
            r'[a-f0-9]{64}', value['configuration_fingerprint']):
        return False
    if value.get('action') == 'read':
        return set(value) == keys
    return (value.get('action') == 'prepare' and set(value) == keys | {'instrument', 'values'}
            and isinstance(value['instrument'], str) and 1 <= len(value['instrument']) <= 1024
            and isinstance(value['values'], dict) and 1 <= len(value['values']) <= 64)


class ResidentInstrumentSettings:
    def __init__(self, editor, configuration, context):
        self.editor, self.configuration, self.context = editor, configuration, context

    def execute(self, request):
        if not valid_request(request):
            raise ValueError('INSTRUMENT_SETTINGS_REQUEST_INVALID')
        fingerprint = self.configuration.fingerprint
        if request['configuration_fingerprint'] != fingerprint:
            raise ValueError('HOST_CONFIGURATION_STALE')
        self.configuration.verify(self.context)
        if self.editor is None or self.context.config_path is None:
            if request['action'] == 'read':
                return {'configuration_fingerprint': fingerprint, 'instruments': []}
            raise ValueError('INSTRUMENT_SETTINGS_UNAVAILABLE')
        try:
            device_id, modules = self.editor.catalogue(self.context.config_path)
            instruments = {instrument_identity(device_id, row['module_id']): row for row in modules}
            if request['action'] == 'read':
                result = {'instruments': [{'id': key, **row} for key, row in instruments.items()]}
            else:
                row = instruments.get(request['instrument'])
                if row is None or not row['fields']:
                    raise ValueError('INSTRUMENT_SETTINGS_UNAVAILABLE')
                result = {'configuration': self.editor.prepare(self.context.config_path,
                    row['module_id'], request['values']), 'driver': self.context.driver_name,
                    'title': f"{row['name']} settings"[:120]}
        except ValueError as error:
            code = getattr(error, 'code', str(error))
            if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', code):
                code = 'INSTRUMENT_SETTINGS_REJECTED'
            raise ValueError(code) from error
        self.configuration.verify(self.context)
        return {**result, 'configuration_fingerprint': fingerprint}


class ConsoleInstrumentSettings(AuthorizedInteractor):
    required_capability = 'configuration:drafts'

    def __init__(self, tokens, repository, resident):
        super().__init__(tokens)
        self.repository, self.resident = repository, resident

    def perform(self, request):
        if not valid_request(request):
            raise ConfigurationError('INSTRUMENT_SETTINGS_REQUEST_INVALID')
        try:
            result = self.resident.execute({'action': 'instrument-settings', 'profile_request': request})
        except OSError as error:
            raise ConfigurationError('INSTRUMENT_SETTINGS_HOST_UNAVAILABLE', 'unavailable') from error
        except ValueError as error:
            raise ConfigurationError(str(error), 'conflict') from error
        fingerprint = request['configuration_fingerprint']
        if result.get('configuration_fingerprint') != fingerprint:
            raise ConfigurationError('HOST_CONFIGURATION_STALE', 'conflict')
        if request['action'] == 'read':
            return result
        configuration = result['configuration']
        encoded = json.dumps(configuration, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(encoded) > 1024 * 1024:
            raise ConfigurationError('INSTRUMENT_SETTINGS_CONFIGURATION_TOO_LARGE')
        draft = self.repository.save(str(uuid4()), 0, {
            'title': result['title'], 'driver': result['driver'], 'configuration': configuration,
            'fingerprint': hashlib.sha256(encoded).hexdigest(),
        }).as_dict()
        return {'draft': {key: draft[key] for key in ('draft_id', 'revision')},
                'configuration_fingerprint': fingerprint}
