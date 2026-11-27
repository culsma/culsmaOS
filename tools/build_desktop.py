"""Build and stage the matching native UI beside the Python console; no separate release."""
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


class DesktopBuild:
    def run(self):
        root = Path(__file__).resolve().parents[1]
        if sys.platform not in {'darwin', 'win32'}:
            raise SystemExit('DESKTOP_BUILD_TARGET_NOT_SUPPORTED')
        frontend = root/'frontend/console'
        version = tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
        platform = 'windows' if sys.platform == 'win32' else 'macos'
        command = [shutil.which('flutter.bat') or 'flutter.bat'] if sys.platform == 'win32' else ['fvm', 'flutter']
        subprocess.run([*command,'build',platform,'--release','--build-name='+version], cwd=frontend, check=True)
        source = frontend/'build/windows/x64/runner/Release' if sys.platform == 'win32' else frontend/'build/macos/Build/Products/Release/culsma_console.app'
        destination = root/'src/culsma_os/console/native'/('windows' if sys.platform == 'win32' else 'culsma_console.app')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=True)
        print('Native console staged for culsma-os desktop; product version '+version)


if __name__ == '__main__':
    DesktopBuild().run()
