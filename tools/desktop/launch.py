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
        self.state = self.user_home / 'Library/Application Support/culsmaOS/preview'
        self.workspace = self.user_home / 'Culsma Preview'
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
        self.seed_file(self.state / 'deck.json', self.resources / 'defaults/deck.json')
        self.seed_file(self.programs / 'Transfer/transfer.culs', self.resources / 'defaults/transfer.culs')

    def command(self, mode):
        shared = ['--home', str(self.workspace), '--program-root', str(self.programs)]
        if mode == 'desktop':
            return ['desktop', '--state-dir', str(self.state), '--resident-socket', str(self.socket), '--driver', 'opentrons-simulator',
                    '--driver-config', str(self.state / 'deck.json'), '--application', str(self.native), *shared]
        if mode == 'mcp':
            return ['mcp', '--socket', str(self.socket), '--drafts-db', str(self.drafts),
                    '--program-store', str(self.snapshots), *shared]
        if mode == 'service':
            return ['serve', '--socket', str(self.socket), '--host-db', str(self.state / 'os.sqlite3'),
                    '--driver', 'opentrons-simulator', '--driver-config', str(self.state / 'deck.json'),
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
        os.environ.update(PYTHONPATH=str(site), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                          CULSMA_OS_STATION_ROOT=str(self.state / 'stations'))
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(site))

    def connection_settings(self):
        return {'mcpServers': {'culsmaOS': {'command': str(self.mcp), 'args': []}}}

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
