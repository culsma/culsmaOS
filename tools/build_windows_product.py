"""Assemble an internal Windows x64 product with a private Python runtime and driver wheels."""
import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit
import tarfile
import zipfile


class WindowsProductBuilder:
    def hamilton_release(self):
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
        dependency, = project['optional-dependencies']['hamilton']
        name, url = dependency.split(' @ ')
        asset = urlsplit(url)
        algorithm, digest = asset.fragment.split('=')
        if (name != 'culsma-driver-hamilton' or algorithm != 'sha256' or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('Invalid Hamilton release pin')
        return {'url': url, 'filename': Path(asset.path).name, 'sha256': digest}

    def verify_hamilton_wheel(self, wheels):
        release = self.hamilton_release()
        wheel = wheels / release['filename']
        if not wheel.is_file() or sha256(wheel.read_bytes()).hexdigest() != release['sha256']:
            raise ValueError('Hamilton wheel does not match the public release')
        return release

    def product_wheels(self, wheels):
        wheel_files = sorted(wheels.glob('*.whl'))
        for required in ('culsma-', 'culsma_os-', 'culsma_driver_hamilton-'):
            if sum(path.name.startswith(required) for path in wheel_files) != 1:
                raise ValueError('PRODUCT_WHEEL_SET_INVALID: ' + required)
        if any(path.name.startswith('culsma_hamilton_agent-') for path in wheel_files):
            raise ValueError('PRODUCT_WHEEL_SET_INVALID: standalone Hamilton Agent')
        return wheel_files

    def build(self, runtime, native, wheels, defaults, output, vc_runtime, source_manifest):
        if sys.platform != 'win32':
            raise ValueError('WINDOWS_BUILD_REQUIRED')
        root = Path(__file__).resolve().parents[1]
        expected = json.loads((root/'tools/windows/python-runtime.json').read_text())
        if sha256(runtime.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('PYTHON_RUNTIME_HASH_MISMATCH')
        if output.exists():
            raise ValueError('OUTPUT_MUST_BE_NEW')
        if not (native/'culsma_console.exe').is_file():
            raise ValueError('NATIVE_BUILD_REQUIRED')
        product = output/'CulsmaOS'
        product.mkdir(parents=True)
        unpack = output/'unpack';unpack.mkdir()
        with tarfile.open(runtime) as archive:
            archive.extractall(unpack, filter='data')
        shutil.move(unpack/'python', product/'runtime')
        unpack.rmdir()
        python = product/'runtime/python.exe'
        wheel_files = self.product_wheels(wheels)
        driver_release = self.verify_hamilton_wheel(wheels)
        wheel_requirements = [
            str(path) + '[mcp]' if path.name.startswith('culsma_os-') else str(path)
            for path in wheel_files
        ]
        subprocess.run([str(python), '-X', 'utf8', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location',
                        *wheel_requirements], check=True)
        subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
        shutil.copytree(native, product/'Native')
        if not (vc_runtime/'msvcp140.dll').is_file() or not (vc_runtime/'vcruntime140.dll').is_file():
            raise ValueError('MSVC_X64_RUNTIME_REQUIRED')
        for dll in vc_runtime.glob('*.dll'):
            shutil.copy2(dll, product/'Native'/dll.name)
        shutil.copy2(root/'tools/windows/launch.py', product/'launch.py')
        shutil.copy2(root/'tools/windows/prepare_upgrade.py', product/'prepare_upgrade.py')
        (product/'defaults').mkdir()
        for name in ('deck.json', 'loadout.json', 'transfer.culs'):
            shutil.copyfile(defaults/name, product/'defaults'/name)
        (product/'defaults/station.json').write_text(json.dumps({'driver':'hamilton-local'})+'\n', encoding='utf-8')
        shutil.copy2(root/'tools/windows/install.ps1', output/'Install.ps1')
        (output/'Install.cmd').write_bytes(b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"\r\npause\r\n')
        for name, mode in [('CulsmaOS', 'desktop'), ('Station status', 'status'), ('Stop station', 'stop')]:
            (product/(name+'.cmd')).write_bytes(('@echo off\r\n"%~dp0runtime\\python.exe" -X utf8 -I "%~dp0launch.py" '+mode+'\r\npause\r\n').encode())
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
            shutil.copy2(root/name, product/name)
        packages = []
        for item in importlib.metadata.distributions(path=[str(product/'runtime/Lib/site-packages')]):
            packages.append({'name':item.metadata['Name'], 'version':item.version})
        inventory = {'platform':'windows-x64', 'minimum_windows':'Windows 10 1809',
            'release_status':'internal validation build; unsigned', 'default_driver':'hamilton-local',
            'physical_execution_enabled':False, 'python':expected,
            'sources':json.loads(source_manifest.read_text(encoding='utf-8-sig')),
            'packages':sorted(packages, key=lambda item:item['name'].lower()),
            'hamilton_release':driver_release,
            'input_wheels':{p.name:sha256(p.read_bytes()).hexdigest() for p in wheel_files},
            'defaults':{p.name:sha256(p.read_bytes()).hexdigest() for p in (product/'defaults').iterdir() if p.is_file()}}
        (product/'Product.json').write_text(json.dumps(inventory,indent=2)+'\n', encoding='utf-8')
        # Entry point executables installed by pip contain build-time interpreter paths.
        # Product entry points always select the bundled runtime instead.
        shutil.rmtree(product/'runtime/Scripts', ignore_errors=True)
        for path in list(product.rglob('__pycache__')):
            shutil.rmtree(path, ignore_errors=True)
        for path in product.rglob('direct_url.json'):
            path.unlink()
        (output/'Read me.txt').write_text(
            'CulsmaOS Windows Preview — internal validation build\n'
            'Windows 10 1809 x64 or newer. Extract the entire archive, then run Install.cmd.\n'
            'A new installation defaults to Hamilton local simulation. An upgrade keeps the existing station configuration.\n'
            'User state: %LOCALAPPDATA%\\CulsmaOS\\windows-preview. Experiments: %USERPROFILE%\\Culsma Hamilton.\n'
            'The installer preserves the VENUS installation and existing physical execution setting.\n'
            'The bundled Hamilton driver connects directly to the installed VENUS Web API.\n'
            'In System Settings, pair an MCP client and enable Remote access. Connect to station loopback port 8768 through a private tunnel.\n'
            'The desktop restores your remote access preference at startup. Closing the desktop closes the listener. Revoke paired credentials in Settings.\n'
            'Close the desktop before upgrading. Install.cmd replaces the entire product and retains the previous installation as a backup.\n'
            'For an existing paired station upgrading from a build without a saved remote preference, run Install.ps1 -RestoreRemoteAccess -Start.\n'
            'Hamilton labware geometry is generated from the packaged Culsma profiles. VENUS and instrument SDKs are installed separately.\n'
            'Closing the window keeps the resident alive. Use Stop station.cmd for a controlled station shutdown.\n', encoding='utf-8')
        archive = output.parent/(output.name+'.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in output.rglob('*'):
                if path.is_file():
                    bundle.write(path, path.relative_to(output))
        archive.with_suffix('.sha256').write_text(sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
        print(str(archive))
        return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime','native','wheels','defaults','output','vc-runtime','source-manifest'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    WindowsProductBuilder().build(args.runtime,args.native,args.wheels,args.defaults,args.output,args.vc_runtime,
                                  args.source_manifest)
