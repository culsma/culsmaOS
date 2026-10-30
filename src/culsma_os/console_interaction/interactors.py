"""Shared, authorized console interaction use cases for humans and automation."""
from dataclasses import asdict
import re
import time
from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.program_manager.models import ConsoleReadRequest
from .models import ViewInteractionError, ViewStateReadRequest, ViewRequest, RendererSessionRequest, RendererSession, ViewReceipt

VIEWS = {'desktop', 'experiment', 'workstation', 'files', 'settings', 'system_info', 'developer', 'editor'}


def validate_identifier(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.:/-]{1,256}', value) is None:
        raise ViewInteractionError('CONSOLE_VIEW_ID_INVALID')


def validate_view_entity(view,value):
    if view=='editor':
        if not isinstance(value,str) or not 1<=len(value)<=240 or '\x00' in value:
            raise ViewInteractionError('CONSOLE_VIEW_ID_INVALID')
    else:validate_identifier(value)


def validate_revision(value):
    if type(value) is not int or value < 0:
        raise ViewInteractionError('CONSOLE_VIEW_REVISION_INVALID')


def validate_view_state(state):
    if (not isinstance(state, dict) or set(state) != {'view', 'entity_id', 'selected_entity_id', 'dirty', 'busy'}
            or not isinstance(state['view'], str) or state['view'] not in VIEWS
            or type(state['dirty']) is not bool or type(state['busy']) is not bool):
        raise ViewInteractionError('CONSOLE_VIEW_STATE_INVALID')
    for key in ['entity_id', 'selected_entity_id']:
        if state[key] is not None:
            validate_view_entity(state['view'],state[key]) if key=='entity_id' else validate_identifier(state[key])
    return dict(state)


def session_view(session, now, lease):
    value = RendererSession(**{key: session[key] for key in ['session_id', 'epoch', 'revision', 'last_seen', 'state']})
    return asdict(value) | {
        'online': not session['closed'] and session['last_seen'] + lease > now,
        'source': 'renderer_report'}


def receipt_view(record, session, now, lease):
    status, outcome = record['status'], record['outcome']
    if status == 'accepted' and (record['expires_at'] <= now or not session
            or session['closed'] or session['epoch'] != record['epoch'] or session['last_seen'] + lease <= now):
        status, outcome = 'expired', 'renderer_unavailable_or_request_expired'
    value = ViewReceipt(record['request_id'], status, record['session_id'], record['epoch'], outcome)
    return asdict(value) | {key: record[key] for key in ['created_at', 'expires_at']} | {
        'status': status, 'outcome': outcome, 'request': record['payload'], 'source': 'presentation_receipt'}


class ViewStateReadInteractor(AuthorizedInteractor):
    required_capability = 'console:views:read'

    def __init__(self, tokens, repository, clock=time.time, lease=15):
        super().__init__(tokens)
        self.repository, self.clock, self.lease = repository, clock, lease

    def perform(self, request):
        if not isinstance(request, ViewStateReadRequest):
            raise ViewInteractionError('CONSOLE_VIEW_READ_INVALID')
        now = self.clock()
        if request.action == 'sessions' and request.request_id is None:
            return {'sessions': [session_view(row, now, self.lease) for row in self.repository.sessions()],
                    'activity': self.repository.activities(latest=True)}
        if request.action != 'receipt':
            raise ViewInteractionError('CONSOLE_VIEW_READ_INVALID')
        validate_identifier(request.request_id)
        record = self.repository.receipt(request.request_id)
        if record is None:
            raise ViewInteractionError('CONSOLE_VIEW_REQUEST_NOT_FOUND', 'not_found')
        return receipt_view(record, self.repository.session(record['session_id']), now, self.lease)


class ViewRequestInteractor(AuthorizedInteractor):
    required_capability = 'console:views:request'

    def __init__(self, tokens, repository, observation, clock=time.time, lease=15, lifetime=30, documents=None):
        super().__init__(tokens)
        self.repository, self.observation = repository, observation
        self.documents=documents
        self.clock, self.lease, self.lifetime = clock, lease, lifetime

    def perform(self, request):
        self.validate_request(request)
        payload = asdict(request)
        existing = self.repository.receipt(request.request_id)
        now = self.clock()
        if existing is not None:
            if existing['payload'] != payload:
                raise ViewInteractionError('CONSOLE_VIEW_REQUEST_CONFLICT', 'conflict')
            return receipt_view(existing, self.repository.session(request.session_id), now, self.lease)
        session = self.repository.session(request.session_id)
        if session is None or session['closed'] or session['last_seen'] + self.lease <= now:
            raise ViewInteractionError('CONSOLE_RENDERER_UNAVAILABLE', 'unavailable')
        if session['epoch'] != request.epoch or session['revision'] != request.expected_revision:
            raise ViewInteractionError('CONSOLE_VIEW_REVISION_CONFLICT', 'conflict')
        self.validate_target(request)
        record = self.repository.enqueue(payload, now, self.lease, self.lifetime)
        return receipt_view(record, self.repository.session(request.session_id), now, self.lease)

    def validate_request(self, request):
        if not isinstance(request, ViewRequest) or not isinstance(request.action, str) or request.action not in {'open', 'reveal'}:
            raise ViewInteractionError('CONSOLE_VIEW_REQUEST_INVALID')
        for value in [request.request_id, request.session_id, request.epoch]:
            validate_identifier(value)
        validate_revision(request.expected_revision)
        if not isinstance(request.view, str) or request.view not in VIEWS:
            raise ViewInteractionError('CONSOLE_VIEW_UNSUPPORTED')
        if request.entity_id is not None:
            validate_view_entity(request.view,request.entity_id)
        if request.view in {'experiment','editor'} and request.entity_id is None:
            raise ViewInteractionError('CONSOLE_VIEW_TARGET_REQUIRED')
        if request.action == 'reveal' and (request.view != 'workstation' or request.entity_id is None):
            raise ViewInteractionError('CONSOLE_VIEW_REVEAL_UNSUPPORTED')
        if request.view in {'desktop', 'files', 'settings', 'system_info', 'developer'} and request.entity_id is not None:
            raise ViewInteractionError('CONSOLE_VIEW_TARGET_UNEXPECTED')

    def validate_target(self, request):
        if request.view == 'editor':
            if self.documents is None:raise ViewInteractionError('CONSOLE_VIEW_UNSUPPORTED')
            from culsma_os.file_system.models import FileReadError
            try:self.documents.read(request.entity_id)
            except FileReadError as error:raise ViewInteractionError(error.code,error.kind) from error
        elif request.view == 'experiment':
            self.observation.execute(ConsoleReadRequest('run', request.entity_id))
        elif request.view == 'workstation' and request.entity_id is not None:
            envelope = self.observation.execute(ConsoleReadRequest('station')).data.get('layout')
            if request.entity_id not in self.layout_entities(envelope):
                raise ViewInteractionError('CONSOLE_VIEW_TARGET_NOT_FOUND', 'not_found')

    def layout_entities(self, envelope):
        if not isinstance(envelope, dict) or envelope.get('status') != 'available':
            return set()
        layout = envelope.get('layout') or {}
        definition, configuration = layout.get('definition') or {}, layout.get('configuration') or {}
        entities = {row['id'] for row in definition.get('objects', []) if isinstance(row, dict) and isinstance(row.get('id'), str)}
        for collection in definition.get('collections', []):
            value = configuration
            path = collection.get('path', '')
            if isinstance(path, str):
                parts = [part.replace('~1', '/').replace('~0', '~') for part in path.strip('/').split('/')]
            elif isinstance(path, list) and all(isinstance(part, str) for part in path):
                parts = path
            else:
                continue
            for key in parts:
                value = value.get(key) if isinstance(value, dict) else None
            if collection.get('keyed') and isinstance(value, dict):
                entities.update(value)
            elif value is not None and isinstance(collection.get('id'), str):
                entities.add(collection['id'])
        return entities


class RendererSessionInteractor(AuthorizedInteractor):
    required_capability = 'console:renderer'

    def __init__(self, tokens, repository, clock=time.time, lease=15):
        super().__init__(tokens)
        self.repository, self.clock, self.lease = repository, clock, lease

    def perform_authorized(self, caller, request):
        if not isinstance(request, RendererSessionRequest) or not isinstance(request.action, str) or request.action not in {'register', 'poll', 'acknowledge', 'close', 'inspect', 'heartbeat'}:
            raise ViewInteractionError('CONSOLE_RENDERER_REQUEST_INVALID')
        validate_revision(request.activity_after)
        now = self.clock()
        if request.action == 'register':
            if any(getattr(request, key) is not None for key in ['session_id', 'epoch', 'revision', 'request_id', 'outcome']):
                raise ViewInteractionError('CONSOLE_RENDERER_REQUEST_INVALID')
            session = self.repository.create_session(caller.subject, now, validate_view_state(request.state))
            self.validate_session_owner(session, caller.subject, session['epoch'], now)
            return {'session': session_view(session, now, self.lease), 'requests': [],
                    'activity': self.repository.activities(latest=True)}
        for value in [request.session_id, request.epoch]:
            validate_identifier(value)
        validate_revision(request.revision)
        session = self.repository.session(request.session_id)
        self.validate_session_owner(session, caller.subject, request.epoch, now)
        if request.action in {'inspect', 'heartbeat'}:
            if request.state is not None or request.request_id is not None or request.outcome is not None:
                raise ViewInteractionError('CONSOLE_RENDERER_REQUEST_INVALID')
            if request.action == 'heartbeat':
                session = self.repository.publish(request.session_id, request.epoch, caller.subject,
                    session['revision'], now, session['state'])
            return {'session': session_view(session, now, self.lease), 'requests': []}
        if request.action == 'acknowledge':
            validate_identifier(request.request_id)
            if not isinstance(request.outcome, str) or request.outcome not in {'displayed', 'deferred', 'rejected'}:
                raise ViewInteractionError('CONSOLE_VIEW_ACK_INVALID')
            record = self.repository.receipt(request.request_id)
            if record is None or receipt_view(record, session, now, self.lease)['status'] == 'expired':
                raise ViewInteractionError('CONSOLE_VIEW_ACK_EXPIRED', 'conflict')
            session = self.repository.acknowledge(request.session_id, request.epoch, caller.subject,
                request.revision, request.request_id, request.outcome, validate_view_state(request.state), now)
            return {'session': session_view(session, now, self.lease), 'requests': []}
        if request.request_id is not None or request.outcome is not None:
            raise ViewInteractionError('CONSOLE_RENDERER_REQUEST_INVALID')
        if request.action == 'close' and request.state is not None:
            raise ViewInteractionError('CONSOLE_RENDERER_REQUEST_INVALID')
        state = session['state'] if request.action == 'close' else validate_view_state(request.state)
        revision = session['revision'] if request.action == 'close' else request.revision
        session = self.repository.publish(request.session_id, request.epoch, caller.subject, revision,
            now, state, closed=request.action == 'close')
        pending = self.repository.pending(request.session_id, request.epoch) if request.action == 'poll' else []
        receipts = [receipt_view(row, session, now, self.lease) for row in pending]
        return {'session': session_view(session, now, self.lease),
                'requests': [row for row in receipts if row['status'] == 'accepted'],
                'activity': self.repository.activities(request.activity_after) if request.action == 'poll' else []}

    def validate_session_owner(self, session, owner, epoch, now):
        if session is None or session['owner'] != owner or session['epoch'] != epoch:
            raise ViewInteractionError('CONSOLE_RENDERER_OWNER_MISMATCH', 'forbidden')
        if session['closed'] or session['last_seen'] + self.lease <= now:
            raise ViewInteractionError('CONSOLE_RENDERER_EXPIRED', 'conflict')


class ConsoleActivityInteractor:
    """Observe shared use cases. No credentials, protocol contents or physical evidence."""
    def __init__(self, repository, clock=time.time):
        self.repository, self.clock = repository, clock

    def describe(self, request):
        from culsma_os.file_system.models import FileWorkspaceRequest
        from culsma_os.workspace_manager.models import StationConfigurationRequest, LabwareRequest, ProgramBindingRequest
        from culsma_os.lifecycle_manager.models import ConsoleActivationRequest
        from culsma_os.program_manager.models import ConsoleProgramRequest, SetupInteractionRequest
        if isinstance(request, FileWorkspaceRequest) and request.action in {'create','save','receive'}:
            return {'action': 'file.'+request.action, 'target': request.path, 'view': 'files' if request.action=='receive' else 'editor'}
        if isinstance(request, StationConfigurationRequest) and request.action in {'create','save','import_layout','validate'}:
            return {'action': 'configuration.'+request.action, 'target': request.draft_id, 'view': 'settings'}
        if isinstance(request, ConsoleActivationRequest) and request.action=='apply':
            return {'action': 'configuration.apply_requested', 'target': request.draft_id, 'view': 'settings'}
        if isinstance(request, LabwareRequest) and request.action=='prepare':
            return {'action': 'labware.prepare', 'target': None, 'view': 'workstation'}
        if isinstance(request, ProgramBindingRequest):
            return {'action': 'program.bind', 'target': request.draft_id, 'view': 'settings'}
        if isinstance(request, ConsoleProgramRequest) and request.action in {'inspect','preview','start','submit','pause','resume','cancel'}:
            return {'action': 'program.'+request.action, 'target': request.program_id or request.run_id, 'view': 'files'}
        if isinstance(request, SetupInteractionRequest) and request.action in {'revise','begin'}:
            return {'action': 'loading.'+request.action, 'target': request.run_id, 'view': 'experiment'}
        return None

    def started(self, request, caller):
        value=self.describe(request)
        if value is None:
            return None
        from uuid import uuid4
        value |= {'action_id':str(uuid4()), 'actor':'automation' if caller.subject=='local-mcp-process' else 'operator',
                  'follow': 'console:views:request' in caller.capabilities}
        self.repository.record_activity(value | {'phase':'started', 'time':self.clock()})
        return value

    def finished(self, value, result, error):
        if value is None:
            return
        value=dict(value)
        if error is None and isinstance(result,dict):
            if value['action'].startswith('file.') and isinstance(result.get('path'),str):
                value['target']=result['path']
            if value['view']=='settings' and isinstance(result.get('draft'),dict):
                value['target']=result['draft'].get('draft_id') or value['target']
            if value['action'] in {'program.start','program.submit'}:
                run_id=result.get('run_id') or (result.get('run') or {}).get('run_id')
                if run_id:
                    value.update(view='experiment',target=run_id)
        self.repository.record_activity(value | {'phase':'failed' if error is not None else 'returned',
            'code':getattr(error,'code',None) if error is not None else None, 'time':self.clock()})
