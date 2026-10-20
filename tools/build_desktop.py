"""Build and stage the matching native UI beside the Python console; no separate release."""
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


class DesktopBuild:
    def run(self):
        root = Path(__file__).resolve().parents[1]
        if sys.platform != 'darwin':
            raise SystemExit('DESKTOP_BUILD_TARGET_NOT_VERIFIED: only macOS is currently validated')
        frontend = root/'frontend/console'
        version = tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
        subprocess.run(['fvm','flutter','build','macos','--release','--build-name='+version], cwd=frontend, check=True)
        source = frontend/'build/macos/Build/Products/Release/culsma_console.app'
        destination = root/'src/culsma_os/console/native/culsma_console.app'
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=True)
        print('Native console staged for culsma-os desktop; product version '+version)


if __name__ == '__main__':
    DesktopBuild().run()
