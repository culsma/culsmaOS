"""Package committed backend maintenance changes; retain the installed native UI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def resolve_revision(repository, revision):
    """Freeze a selected git ref before collecting source bytes."""
    return subprocess.check_output(['git', 'rev-parse', '--verify', revision + '^{commit}'],
                                   cwd=repository, text=True).strip()


def committed_files(repository, revision, prefix):
    """Include the full source tree, not just the final commit's diff."""
    names = subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', revision, '--', prefix], cwd=repository, text=True).splitlines()
    return {name[len(prefix):]: subprocess.check_output(
        ['git', 'show', f'{revision}:{name}'], cwd=repository)
        for name in names if name.startswith(prefix)}


def source_overlays(repository, names, prefixes):
    files = {}
    for name in names:
        path = Path(name)
        prefix = next((prefix for prefix in prefixes if name.startswith(prefix)), None)
        if path.is_absolute() or '..' in path.parts or prefix is None or path.suffix != '.py':
            raise ValueError('Explicit driver/OS Python source paths required')
        resolved = (repository / path).resolve()
        if not resolved.is_relative_to(repository.resolve()):
            raise ValueError('Explicit driver/OS source must remain inside its repository')
        source_root = 'agent/src/' if name.startswith('agent/src/') else 'src/'
        files[name[len(source_root):]] = resolved.read_bytes()
    return files


def working_source_changes(repository, revision, prefixes):
    """List source differences, including new files that git diff omits."""
    changed = subprocess.check_output(['git', 'diff', '--name-only', revision, '--', *prefixes],
                                     cwd=repository, text=True).splitlines()
    new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', *prefixes],
                                 cwd=repository, text=True).splitlines()
    return set(changed) | set(new)


def require_source_selection(repository, revision, prefixes, overrides):
    omitted = working_source_changes(repository, revision, prefixes) - set(overrides)
    if omitted:
        raise ValueError('Unselected working source changes; commit them or select explicit overlays: ' + ', '.join(sorted(omitted)))


def prepare(output, os_repository, driver_repository, driver_sources=(), *,
            os_sources=(), os_revision='HEAD', driver_revision='HEAD'):
    os_commit = resolve_revision(os_repository, os_revision)
    driver_commit = resolve_revision(driver_repository, driver_revision)
    require_source_selection(os_repository, os_commit, ('src/',), os_sources)
    require_source_selection(driver_repository, driver_commit, ('src/',), driver_sources)
    files = committed_files(os_repository, os_commit, 'src/')
    files.update(committed_files(driver_repository, driver_commit, 'src/'))
    files.update(source_overlays(os_repository, os_sources, ('src/culsma_os/',)))
    files.update(source_overlays(driver_repository, driver_sources,
        ('src/culsma_driver_hamilton/', 'src/culsma_hamilton_os/')))
    manifest = {'os_backend': os_commit, 'hamilton_backend': driver_commit,
                'source_selection': 'complete_committed_trees_with_explicit_overlays',
                'native_ui': 'retained_installed', 'driver_source_overrides': list(driver_sources),
                'os_source_overrides': list(os_sources),
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output / 'Backend.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('maintenance-patch.json', json.dumps(manifest, indent=2))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (output / 'install.ps1').write_bytes((os_repository / 'tools/windows/install.ps1').read_bytes())
    digest = hashlib.sha256((output / 'Backend.zip').read_bytes()).hexdigest()
    script = r'''$ErrorActionPreference = 'Stop'
$product = Join-Path $env:LOCALAPPDATA 'Programs\CulsmaOS-Remote-Preview'
$stage = Join-Path $PSScriptRoot 'CulsmaOS'
$zip = Join-Path $PSScriptRoot 'Backend.zip'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLower() -ne 'DIGEST') { throw 'Backend hash mismatch' }
if (Test-Path -LiteralPath $stage) { throw 'Staging directory already exists; inspect it before retrying' }
$inventory = Get-Content -Raw (Join-Path $product 'Product.json') | ConvertFrom-Json
if ($inventory.packages.name -contains 'culsma-hamilton-agent') {
  throw 'Use the complete Windows installer to upgrade this product to direct VENUS.'
}
Copy-Item -LiteralPath $product -Destination $stage -Recurse
$python = Join-Path $stage 'runtime\python.exe'
$packages = Join-Path $stage 'runtime\Lib\site-packages'
& $python -I -m zipfile -e $zip $packages
if ($LASTEXITCODE -ne 0) { throw 'Backend extraction failed' }
& $python -I -c "from culsma_os.console.adapters.mcp import MCPServerAdapter; from culsma_driver_hamilton.interactors.native_maintenance_interactor import HamiltonNativeMaintenanceInteractor; from culsma_driver_hamilton.venus.configuration.generated import generated_method_name; assert hasattr(MCPServerAdapter, 'debug_prepare_native_method'); assert generated_method_name('os-native_maintenance-' + 'a'*24)"
if ($LASTEXITCODE -ne 0) { throw 'Backend imports failed; installed product retained' }
$manifest = Get-Content -Raw (Join-Path $packages 'maintenance-patch.json') | ConvertFrom-Json
foreach ($file in $manifest.files.PSObject.Properties) {
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $packages $file.Name)).Hash.ToLower() -ne $file.Value) { throw 'Staged source hash mismatch' }
}
Copy-Item -LiteralPath (Join-Path $packages 'maintenance-patch.json') -Destination (Join-Path $stage 'BackendMaintenance.json')
& (Join-Path $PSScriptRoot 'install.ps1') -RestoreRemoteAccess -Start
if (!$?) { throw 'Product installation failed' }
Write-Host 'MAINTENANCE_BACKEND_INSTALLED_NATIVE_UI_RETAINED'
'''.replace('DIGEST', digest)
    (output / 'Upgrade.ps1').write_text(script, encoding='utf-8')
    return manifest


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--os-repository', type=Path, default=root)
    parser.add_argument('--driver-repository', type=Path, default=root.parent / 'culsma-driver-hamilton')
    parser.add_argument('--os-revision', default='HEAD')
    parser.add_argument('--driver-revision', default='HEAD')
    parser.add_argument('--os-source', action='append', default=[])
    parser.add_argument('--driver-source', action='append', default=[])
    args = parser.parse_args()
    manifest = prepare(args.output, args.os_repository, args.driver_repository,
                       args.driver_source, os_sources=args.os_source,
                       os_revision=args.os_revision, driver_revision=args.driver_revision)
    print(json.dumps({'files': len(manifest['files']), 'native_ui': manifest['native_ui'],
                      'os_backend': manifest['os_backend'], 'hamilton_backend': manifest['hamilton_backend']}))


if __name__ == '__main__':
    main()
