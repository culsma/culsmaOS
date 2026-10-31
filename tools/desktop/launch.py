"""Installed Mac product bootstrap. No credentials, vendor files or developer paths."""
from pathlib import Path
from hashlib import sha256
import json
import stat
import os
import sys


class MacPreviewProduct:
    def __init__(self, resources, home=None, endpoint_root=None):
        self.resources = Path(resources).resolve()
        self.user_home = Path(home) if home is not None else Path.home()
        self.base_state = self.user_home / 'Library/Application Support/culsmaOS/preview'
        selection = self.base_state / 'station.json'
        if selection.is_symlink():
            raise ValueError('PRODUCT_STATION_SELECTION_IS_LINK')
        selected = json.loads(selection.read_text()) if selection.exists() else {'profile':'opentrons-simulator'}
        if not isinstance(selected,dict) or set(selected)!={'profile'}:
            raise ValueError('PRODUCT_STATION_PROFILE_INVALID')
        self.profile = os.environ.get('CULSMA_OS_PROFILE', selected.get('profile'))
        if self.profile not in {'opentrons-simulator','hamilton-local'}:
            raise ValueError('PRODUCT_STATION_PROFILE_INVALID')
        self.addon = self.user_home / 'Library/Application Support/culsmaOS/addons/hamilton'
        self.state = self.base_state if self.profile=='opentrons-simulator' else self.base_state/'stations/hamilton-local'
        self.workspace = self.user_home / ('Culsma Preview' if self.profile=='opentrons-simulator' else 'Culsma Hamilton')
        self.programs = self.workspace / 'projects'
        key = sha256(str(self.state.resolve()).encode()).hexdigest()[:16]
        self.endpoint = Path(endpoint_root or '/private/tmp') / f'culsma-preview-{os.getuid()}-{key}'
        self.socket = self.endpoint / 'station.sock'
        self.snapshots = self.state / 'programs'
        self.drafts = self.state / 'drafts.sqlite3'
        self.native = self.resources / 'Native/culsma_console.app/Contents/MacOS/culsma_console'
        self.mcp = self.resources.parent / 'MacOS/culsma-mcp'

    def private_directory(self, path):
        # Check each directory beneath the user's home, including existing parents.
        current = self.user_home
        for part in path.relative_to(self.user_home).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('PREVIEW_DIRECTORY_IS_LINK')
            current.mkdir(exist_ok=True, mode=0o700)
            if not current.is_dir():
                raise ValueError('PREVIEW_DIRECTORY_UNAVAILABLE')

    def seed_file(self, target, source):
        if target.is_symlink():
            raise ValueError('PREVIEW_FILE_IS_LINK')
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if not target.is_file():
                raise ValueError('PREVIEW_FILE_UNAVAILABLE')
            return
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(source.read_bytes())

    def initialize_endpoint(self):
        try:self.endpoint.mkdir(mode=0o700)
        except FileExistsError:pass
        info = self.endpoint.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('PREVIEW_ENDPOINT_NOT_PRIVATE')

    def initialize(self):
        self.initialize_endpoint()
        for directory in (self.state, self.programs / 'Transfer', self.workspace / 'results'):
            self.private_directory(directory)
        # This preview owns a separate workspace; upgrades never replace user protocols/configuration.
        defaults = self.resources/'defaults' if self.profile=='opentrons-simulator' else self.addon/'defaults'
        self.seed_file(self.state / 'deck.json', defaults / 'deck.json')
        self.seed_file(self.programs / 'Transfer/transfer.culs', defaults / 'transfer.culs')

    def command(self, mode):
        shared = ['--home', str(self.workspace), '--program-root', str(self.programs)]
        if mode == 'desktop':
            return ['desktop', '--state-dir', str(self.state), '--resident-socket', str(self.socket), '--driver', self.profile,
                    '--driver-config', str(self.state / 'deck.json'), '--application', str(self.native), *shared]
        if mode == 'mcp':
            return ['mcp', '--socket', str(self.socket), '--drafts-db', str(self.drafts),
                    '--program-store', str(self.snapshots), *shared]
        if mode == 'service':
            return ['serve', '--socket', str(self.socket), '--host-db', str(self.state / 'os.sqlite3'),
                    '--driver', self.profile, '--driver-config', str(self.state / 'deck.json'),
                    '--station-id', 'desktop', '--artifacts-dir', str(self.state / 'runs')]
        if mode in {'status', 'stop'}:
            return ['host-status' if mode == 'status' else 'host-stop', '--socket', str(self.socket)]
        raise ValueError('PREVIEW_COMMAND_INVALID')

    def configure_environment(self, mode):
        site = self.resources / ('packages/mcp' if mode == 'mcp' else 'packages/simulator')
        if not site.is_dir():
            raise ValueError('PREVIEW_PACKAGES_MISSING')
        # The bootstrap is invoked with -I. Children inherit only the selected bundled packages.
        for name in tuple(os.environ):
            if name.startswith(('PYTHON', 'DYLD_')):
                os.environ.pop(name)
        paths=[str(site)]
        if self.profile=='hamilton-local':
            if not (self.addon/'packages').is_dir() or not (self.addon/'LabWare').is_dir():
                raise ValueError('HAMILTON_LOCAL_ADDON_NOT_INSTALLED')
            paths.append(str(self.addon/'packages'))
            os.environ.update(CULSMA_HAMILTON_LABWARE_ROOT=str(self.addon/'LabWare'),
                CULSMA_HAMILTON_LOCAL_LOADOUT=str(self.addon/'defaults/loadout.json'),
                CULSMA_HAMILTON_LOCAL_MAGNETIC_LOADOUT=str(self.addon/'profiles/magnetic/loadout.json'),
                CULSMA_HAMILTON_LOCAL_WORKSPACE=str(self.state/'local-model'))
            sys.path.insert(0,str(self.addon/'packages'))
        os.environ.update(CULSMA_OS_STATION_SELECTION_FILE=str(self.base_state/'station.json'),
            CULSMA_OS_PRODUCT_PROFILE=self.profile,
            CULSMA_OS_STATION_PROFILES=json.dumps(self.station_profiles()))
        os.environ.update(PYTHONPATH=os.pathsep.join(paths), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                          CULSMA_OS_STATION_ROOT=str(self.state / 'stations'))
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(site))

    def station_profiles(self):
        return [
            {'id':'opentrons-simulator','label':'Opentrons official simulator','driver':'opentrons-simulator',
             'required_paths':[str(self.resources/'defaults/deck.json'),str(self.resources/'packages/simulator')]},
            {'id':'hamilton-local','label':'Hamilton local simulation','driver':'hamilton-local',
             'required_paths':[str(self.addon/name) for name in ('packages','LabWare','defaults/deck.json','defaults/loadout.json','defaults/transfer.culs')]},
        ]

    def select_profile(self, profile):
        from culsma_os.auth.interactors import TokenInteractor
        from culsma_os.auth.repository import SessionCredentialRepository
        from culsma_os.lifecycle_manager.interactors import StationSelectionInteractor
        from culsma_os.lifecycle_manager.repository import FileStationSelectionRepository
        from culsma_os.lifecycle_manager.models import StationSelectionRequest
        tokens=TokenInteractor(SessionCredentialRepository())
        repository=FileStationSelectionRepository(self.base_state/'station.json',self.station_profiles(),'opentrons-simulator')
        owner=StationSelectionInteractor(tokens,repository,self.profile)
        credential='Bearer '+tokens.issue_console_session()
        current=owner.execute(credential,StationSelectionRequest('status'))
        return owner.execute(credential,StationSelectionRequest('select',profile,current['selected_profile']))

    def connection_settings(self):
        return {'mcpServers': {'culsma_os': {'command': str(self.mcp), 'args': []}}}

    def write_connection_settings(self):
        # Generated for the installed location; no identity or access token is stored here.
        target = self.state / 'mcp-config.json'
        if target.is_symlink():
            raise ValueError('PREVIEW_FILE_IS_LINK')
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(self.connection_settings(), stream, indent=2)
            stream.write('\n')

    def run(self, mode):
        if mode.startswith('select-'):
            self.configure_environment('mcp')
            print(json.dumps(self.select_profile(mode.removeprefix('select-'))))
            return
        arguments = self.command(mode)
        self.initialize()
        self.configure_environment(mode)
        if mode == 'desktop':
            self.write_connection_settings()
        from culsma_os.cli import CulsmaOSCLI
        CulsmaOSCLI.main(arguments)


if __name__ == '__main__':
    try:
        MacPreviewProduct(Path(__file__).parent).run(sys.argv[1] if len(sys.argv) == 2 else '')
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
