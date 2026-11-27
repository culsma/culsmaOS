"""Windows product entry point. Persistent state stays outside the installed bundle."""
import ctypes
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import sys
import traceback


class WindowsProduct:
    def __init__(self, resources, state=None, home=None):
        self.resources = Path(resources).resolve()
        self.state = Path(state or Path(os.environ['LOCALAPPDATA']) / 'CulsmaOS/windows-preview')
        self.home = Path(home or Path.home() / 'Culsma Hamilton')
        self.socket = self.state / 'station.endpoint'
        self.native = self.resources / 'Native/culsma_console.exe'

    def seed(self, destination, source):
        from culsma_os.platform_support import HostFileIO
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = HostFileIO.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | HostFileIO.O_NOFOLLOW, private=True)
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file():
                raise ValueError('PRODUCT_CONFIGURATION_UNAVAILABLE')
            return
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source.read_bytes())

    def initialize(self):
        if sys.platform != 'win32' or sys.getwindowsversion().build < 17763:
            raise ValueError('Windows 10 version 1809 or newer is required.')
        self.state.mkdir(parents=True, exist_ok=True)
        from culsma_os.platform_support import HostFileIO
        descriptor = HostFileIO.open(self.state, os.O_RDONLY | HostFileIO.O_DIRECTORY | HostFileIO.O_NOFOLLOW)
        HostFileIO.close(descriptor)
        self.seed(self.state/'station.json', self.resources/'defaults/station.json')
        self.seed(self.state/'deck.json', self.resources/'defaults/deck.json')
        self.seed(self.state/'loadout.json', self.resources/'defaults/loadout.json')
        self.seed(self.home/'projects/Transfer/transfer.culs', self.resources/'defaults/transfer.culs')
        (self.home/'results').mkdir(parents=True, exist_ok=True)
        os.environ.update(PYTHONUTF8='1', PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                          CULSMA_OS_STATION_ROOT=str(self.state/'stations'),
                          CULSMA_HAMILTON_LOCAL_LOADOUT=str(self.state/'loadout.json'),
                          CULSMA_HAMILTON_LOCAL_WORKSPACE=str(self.state/'local-model'))
        old_state = self.state / 'agent'
        old_configuration = old_state / 'agent.json'
        os.environ['CULSMA_HAMILTON_VENUS_WORKSPACE'] = str(
            old_state if old_configuration.is_file() else self.state / 'venus')
        os.environ.pop('CULSMA_HAMILTON_VENUS_LEGACY_CONFIG', None)
        if old_configuration.is_file():
            os.environ['CULSMA_HAMILTON_VENUS_LEGACY_CONFIG'] = str(old_configuration)
        # The resident, preparer and native execution use the same station-owned catalogue.
        os.environ.pop('CULSMA_HAMILTON_PRIVATE_LABWARE', None)
        os.environ.pop('CULSMA_HAMILTON_LABWARE_ROOT', None)
        os.environ['CULSMA_HAMILTON_HEAD96_LAYOUT_DIR'] = str(self.state / 'hamilton' / 'layouts')
        station = json.loads((self.state/'station.json').read_text(encoding='utf-8'))
        if station.get('driver') not in {'hamilton-local', 'hamilton-venus', 'hamilton-agent'}:
            raise ValueError('WINDOWS_STATION_DRIVER_INVALID')
        return station

    def run(self, mode='desktop'):
        station = self.initialize()
        from culsma_os.cli import CulsmaOSCLI
        if mode in {'status', 'stop'}:
            return CulsmaOSCLI.main(['host-status' if mode == 'status' else 'host-stop', '--socket', str(self.socket)])
        if mode != 'desktop':
            raise ValueError('PRODUCT_COMMAND_INVALID')
        if not self.native.is_file():
            raise ValueError('The desktop component is missing; reinstall this package.')
        return CulsmaOSCLI.main(['desktop', '--remote-access', '--state-dir', str(self.state), '--resident-socket', str(self.socket),
            '--driver', station['driver'], '--driver-config', str(self.state/'deck.json'),
            '--application', str(self.native), '--home', str(self.home), '--program-root', str(self.home/'projects')])


if __name__ == '__main__':
    try:
        product = WindowsProduct(Path(__file__).parent)
        product.state.mkdir(parents=True, exist_ok=True)
        with (product.state/'startup.log').open('a', encoding='utf-8', buffering=1) as log:
            with redirect_stdout(log), redirect_stderr(log):
                product.run(sys.argv[1] if len(sys.argv) == 2 else 'desktop')
    except SystemExit as error:
        if error.code not in (None, 0):
            ctypes.windll.user32.MessageBoxW(None, 'CulsmaOS could not start. See startup.log in your CulsmaOS data folder.', 'CulsmaOS', 0x10)
        raise
    except Exception:
        state = Path(os.environ['LOCALAPPDATA'])/'CulsmaOS/windows-preview'
        state.mkdir(parents=True, exist_ok=True)
        (state/'startup.log').write_text(traceback.format_exc(), encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(None, 'CulsmaOS could not start. See startup.log in your CulsmaOS data folder.', 'CulsmaOS', 0x10)
        raise SystemExit(2)
