"""Assemble the local arm64 preview from verified runtime, wheels and native UI."""
import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tomllib


class MacProductBuilder:
    def digest(self, path):
        return sha256(path.read_bytes()).hexdigest()

    def clean_python_tree(self, root):
        for path in list(root.rglob('__pycache__')):
            if path.is_dir():shutil.rmtree(path)
        for pattern in ('*.pyc', 'direct_url.json'):
            for path in root.rglob(pattern):path.unlink()
        # Entry points contain build-machine shebangs. Product launchers select the bundled runtime.
        for directory in root.glob('packages/*/bin'):
            shutil.rmtree(directory)

    def package_inventory(self, packages):
        result={}
        for environment in ('simulator','mcp'):
            result[environment]=[]
            for distribution in importlib.metadata.distributions(path=[str(packages/environment)]):
                licenses=[str(p) for p in distribution.files or [] if any(word in str(p).lower() for word in ('license','notice','copying'))]
                result[environment].append({'name':distribution.metadata['Name'],'version':distribution.version,
                    'license':distribution.metadata.get('License-Expression') or distribution.metadata.get('License',''),
                    'license_files':licenses})
            result[environment].sort(key=lambda r:r['name'].lower())
        return result

    def validate_native_paths(self, native):
        for name in ('Contents/MacOS/culsma_console',
                     'Contents/Frameworks/App.framework/Versions/A/App'):
            if str(Path.home()).encode() in (native/name).read_bytes():
                raise ValueError('NATIVE_PERSONAL_BUILD_PATH: build from a neutral source archive')

    def write_shell(self, path, mode):
        path.write_text('#!/bin/sh\nset -eu\nRESOURCES="$(CDPATH= cd -- "$(dirname -- "$0")/../Resources" && pwd)"\n'
            'exec "$RESOURCES/runtime/bin/python3.11" -I -B "$RESOURCES/launch.py" '+mode+'\n')
        path.chmod(0o755)

    def create_icon(self, root, resources, output):
        iconset=output/'Culsma.iconset';iconset.mkdir()
        for size in (16,32,128,256,512):
            for scale in (1,2):
                target=iconset/f'icon_{size}x{size}{"@2x" if scale==2 else ""}.png'
                subprocess.run(['/usr/bin/sips','-z',str(size*scale),str(size*scale),
                    str(root/'assets/culsma-logo.png'),'--out',str(target)],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['/usr/bin/iconutil','-c','icns',str(iconset),'-o',str(resources/'AppIcon.icns')],check=True)
        shutil.rmtree(iconset)

    def sign(self, app):
        resources=app/'Contents/Resources'
        candidates=[]
        for parent in (resources/'runtime',resources/'packages'):
            candidates.extend(p for p in parent.rglob('*') if p.is_file() and not p.is_symlink()
                and (p.suffix in {'.so','.dylib'} or p.name=='python3.11'))
        for path in candidates:
            subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(resources/'Native/culsma_console.app')],check=True)
        subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(app)],check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)

    def build(self, runtime_archive, licenses_archive, packages, native, output):
        if sys.platform!='darwin' or os.uname().machine!='arm64':raise ValueError('MAC_ARM64_BUILD_REQUIRED')
        root=Path(__file__).resolve().parents[1]
        version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
        lock=json.loads((root/'tools/desktop/python-runtime.json').read_text())
        if self.digest(runtime_archive)!=lock['sha256'] or self.digest(licenses_archive)!=lock['licenses']['sha256']:
            raise ValueError('PYTHON_ARCHIVE_HASH_MISMATCH')
        if output.exists():raise ValueError('MAC_OUTPUT_MUST_BE_NEW')
        if not (native/'Contents/MacOS/culsma_console').is_file():raise ValueError('NATIVE_BUILD_REQUIRED')
        output.mkdir(parents=True)
        image=output/'image';image.mkdir()
        app=image/'CulsmaOS Preview.app';contents=app/'Contents';resources=contents/'Resources'
        resources.mkdir(parents=True);(contents/'MacOS').mkdir()
        unpack=output/'unpack';unpack.mkdir()
        with tarfile.open(runtime_archive) as archive:archive.extractall(unpack,filter='data')
        shutil.move(unpack/'python',resources/'runtime');unpack.rmdir()
        # The product needs the interpreter, not a second system of package-management tools.
        shutil.rmtree(resources/'runtime/lib/python3.11/site-packages')
        for path in (resources/'runtime/bin').iterdir():
            if path.name not in {'python','python3','python3.11'}:path.unlink()
        # macOS bsdtar supports the upstream zstandard archive; copy license inventory only.
        license_unpack=output/'license-unpack';license_unpack.mkdir()
        subprocess.run(['/usr/bin/tar','-xf',str(licenses_archive.resolve()),'-C',str(license_unpack),
            'python/PYTHON.json','python/licenses'],check=True)
        metadata=json.loads((license_unpack/'python/PYTHON.json').read_text())
        if metadata['python_version']!=lock['version'] or metadata['target_triple']!=lock['target']:
            raise ValueError('PYTHON_LICENSE_INVENTORY_MISMATCH')
        shutil.move(license_unpack/'python',resources/'PythonLicenses');shutil.rmtree(license_unpack)
        shutil.copytree(packages,resources/'packages',symlinks=True)
        shutil.copytree(native,resources/'Native/culsma_console.app',symlinks=True)
        for name in ('Contents/MacOS/culsma_console','Contents/Frameworks/App.framework/Versions/A/App'):
            subprocess.run(['/usr/bin/xcrun','strip','-S','-x',str(resources/'Native/culsma_console.app'/name)],check=True)
        self.validate_native_paths(resources/'Native/culsma_console.app')
        shutil.copy2(root/'tools/desktop/launch.py',resources/'launch.py')
        defaults=resources/'defaults';defaults.mkdir()
        for name in ('deck.json','transfer.culs'):shutil.copy2(root/'examples/transfer'/name,defaults/name)
        for name in ('LICENSE','THIRD_PARTY_NOTICES.md'):
            shutil.copy2(root/name,resources/name)
        shutil.copy2(root/'docs/mac-preview.md',image/'Read me first.md')
        shutil.copy2(root/'docs/mac-preview.md',resources/'Read me first.md')
        self.clean_python_tree(resources)
        # Wheel/site metadata is included with all third-party license files.
        inventory=self.package_inventory(resources/'packages')
        if not all(any(p['name']=='culsma-os' and p['version']==version for p in items) for items in inventory.values()):
            raise ValueError('PRODUCT_OS_VERSION_MISMATCH')
        pins=json.loads((root/'tools/desktop/dependencies-lock.json').read_text())
        for name,rows in inventory.items():
            actual={row['name'].lower().replace('_','-'):row['version'] for row in rows if row['name']!='culsma-os'}
            expected={row['name'].lower().replace('_','-'):row['version'] for row in pins['environments'][name]}
            if actual!=expected:raise ValueError('PRODUCT_DEPENDENCIES_CHANGED')
        product={'version':version,'platform':'macos-arm64','runtime':lock,'packages':inventory,
            'signing':'ad-hoc, not Developer ID notarized','hardware':'simulation-only preview',
            'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()}
        (resources/'Product.json').write_text(json.dumps(product,indent=2)+'\n')
        self.write_shell(contents/'MacOS/culsma-mcp','mcp')
        self.write_shell(contents/'MacOS/culsma-status','status')
        self.write_shell(contents/'MacOS/culsma-stop','stop')
        subprocess.run(['/usr/bin/xcrun','swiftc','-O','-target','arm64-apple-macos13.0',
            str(root/'tools/desktop/Launcher.swift'),'-o',str(contents/'MacOS/culsmaOS')],check=True)
        self.create_icon(root,resources,output)
        native_resources=resources/'Native/culsma_console.app/Contents/Resources'
        shutil.copy2(resources/'AppIcon.icns',native_resources/'AppIcon.icns')
        info={'CFBundleExecutable':'culsmaOS','CFBundleIdentifier':'dev.culsma.os.preview',
            'CFBundleName':'CulsmaOS Preview','CFBundleDisplayName':'CulsmaOS Preview',
            'CFBundlePackageType':'APPL','CFBundleShortVersionString':version.split('rc')[0],'CFBundleVersion':'1',
            'CulsmaProductVersion':version,'CFBundleIconFile':'AppIcon.icns',
            'LSMinimumSystemVersion':'15.0','LSUIElement':True,'NSHighResolutionCapable':True}
        (contents/'Info.plist').write_bytes(plistlib.dumps(info))
        (image/'Applications').symlink_to('/Applications',target_is_directory=True)
        self.sign(app)
        print(str(app))
        return app

    def image(self, output, version):
        dmg=output/f'culsmaOS-{version}-macOS-arm64.dmg'
        subprocess.run(['/usr/bin/hdiutil','create','-fs','HFS+','-format','UDZO',
            '-volname','CulsmaOS Preview','-srcfolder',str(output/'image'),str(dmg)],check=True)
        (output/'SHA256SUMS').write_text(self.digest(dmg)+'  '+dmg.name+'\n')
        return dmg


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime-archive','licenses-archive','packages','native','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--dmg',action='store_true')
    args=parser.parse_args();builder=MacProductBuilder()
    app=builder.build(args.runtime_archive,args.licenses_archive,args.packages,args.native,args.output)
    if args.dmg:print(builder.image(args.output,json.loads((app/'Contents/Resources/Product.json').read_text())['version']))
