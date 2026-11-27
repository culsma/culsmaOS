"""Station-managed bearer grants. Only digests are stored on the station."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from secrets import token_urlsafe

from culsma_os.auth.models import CallerContext, ConsoleAccessError
from culsma_os.auth.interactors import AUTOMATION_CAPABILITIES
from culsma_os.platform_support import HostFileIO

TOKEN_PATTERN = re.compile(r'[A-Za-z0-9_-]{43,128}')
SUBJECT_PATTERN = re.compile(r'[A-Za-z0-9_.@-]{1,128}')


class FileRemoteIdentityAdapter:
    def __init__(self, grants: Path, station_id: str, *, scope='read'):
        if scope not in {'read', 'automation'}:
            raise ValueError('REMOTE_GRANT_SCOPE_INVALID')
        self.grants = grants
        self.station_id = station_id
        self.scope = scope

    def issue(self, subject, hours, token_file):
        if SUBJECT_PATTERN.fullmatch(subject) is None or not 1 <= hours <= 24 * 30:
            raise ValueError('REMOTE_GRANT_INVALID')
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        grant_file, token = self._issue(subject, expires_at)
        try:
            self.write_new(token_file, token + '\n')
        except BaseException:
            grant_file.unlink()
            raise
        return grant_file

    def pair(self, subject):
        if (self.scope != 'automation' or not isinstance(subject, str)
                or SUBJECT_PATTERN.fullmatch(subject) is None):
            raise ValueError('REMOTE_PAIRING_NAME_INVALID')
        _, token = self._issue(subject, None)
        return token

    def _issue(self, subject, expires_at):
        token = token_urlsafe(32)
        digest = sha256(token.encode('ascii')).hexdigest()
        grant_file = self.grants / f'{digest}.json'
        self.grants.mkdir(mode=0o700, parents=True, exist_ok=True)
        grant = {'subject': subject, 'station_id': self.station_id, 'scope': self.scope,
                 'expires_at': expires_at.isoformat() if expires_at else None}
        self.write_new(grant_file, json.dumps(grant) + '\n')
        return grant_file, token

    def pairings(self):
        result = []
        for path in sorted(self.grants.glob('*.json')):
            if not re.fullmatch(r'[0-9a-f]{64}', path.stem):
                continue
            try:
                grant = json.loads(path.read_text(encoding='utf-8'))
                if (grant['station_id'] == self.station_id and grant['scope'] == self.scope
                        and grant['expires_at'] is None and isinstance(grant['subject'], str)):
                    result.append({'id': path.stem, 'name': grant['subject']})
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return result

    def unpair(self, pairing_id):
        if not isinstance(pairing_id, str) or not re.fullmatch(r'[0-9a-f]{64}', pairing_id):
            raise ValueError('REMOTE_PAIRING_ID_INVALID')
        if any(row['id'] == pairing_id for row in self.pairings()):
            (self.grants / f'{pairing_id}.json').unlink(missing_ok=True)

    @staticmethod
    def write_new(path, content):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | HostFileIO.O_NOFOLLOW
        descriptor = HostFileIO.open(path, flags, private=True)
        try:
            with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
                stream.write(content)
        except BaseException:
            path.unlink()
            raise

    def execute(self, raw_credential):
        if not isinstance(raw_credential, str) or not raw_credential.startswith('Bearer '):
            raise ConsoleAccessError('REMOTE_CREDENTIAL_REQUIRED')
        token = raw_credential[7:]
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise ConsoleAccessError('REMOTE_CREDENTIAL_INVALID')
        digest = sha256(token.encode('ascii')).hexdigest()
        try:
            grant = json.loads((self.grants / f'{digest}.json').read_text(encoding='utf-8'))
            expiry = grant['expires_at']
            if expiry is None:
                if self.scope != 'automation':
                    raise ValueError
            else:
                expires_at = datetime.fromisoformat(expiry)
                if expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
                    raise ValueError
            subject = grant['subject']
            if (grant['station_id'] != self.station_id
                    or grant.get('scope', 'read') != self.scope
                    or not isinstance(subject, str)
                    or SUBJECT_PATTERN.fullmatch(subject) is None):
                raise ValueError
        except (OSError, ValueError, TypeError, KeyError):
            raise ConsoleAccessError('REMOTE_CREDENTIAL_INVALID') from None
        capabilities = (AUTOMATION_CAPABILITIES if self.scope == 'automation'
                        else frozenset({'station:read', f'station:{self.station_id}:read'}))
        return CallerContext(subject, capabilities)
