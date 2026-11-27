param(
    [Parameter(Mandatory=$true)][string]$LanguageSource,
    [Parameter(Mandatory=$true)][string]$SourceManifest,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Root = 'C:\CulsmaBuild'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command exited with code $LASTEXITCODE." }
}
$source = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $Root 'python\python.exe'
$flutter = Join-Path $Root 'flutter\bin\flutter.bat'
$env:PATH = "$Root\git\cmd;$Root\flutter\bin;$Root\python;$env:PATH"
$frontend = Join-Path $source 'frontend\console'
$version = (& $flutter --version --machine | ConvertFrom-Json).frameworkVersion
$expected = (Get-Content (Join-Path $frontend '.fvmrc') -Raw | ConvertFrom-Json).flutter
if ($version -ne $expected) { throw "Flutter $expected required; found $version." }
Push-Location $frontend
try {
    Invoke-Checked $flutter @('pub','get','--enforce-lockfile')
    Invoke-Checked $flutter @('test','--no-pub','test/console/remote_access_settings_test.dart')
    Invoke-Checked $flutter @('build','windows','--release','--no-pub')
} finally { Pop-Location }
$wheels = "$Output.wheels"
New-Item -ItemType Directory -Path $wheels | Out-Null
Invoke-Checked $python @('-m','pip','wheel','--no-deps','--wheel-dir',$wheels,$LanguageSource,$source)
Push-Location (Join-Path $source 'tools')
try {
    $driverUrl = & $python -c "from build_windows_product import WindowsProductBuilder; print(WindowsProductBuilder().hamilton_release()['url'])"
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the pinned Hamilton wheel.' }
    Invoke-Checked $python @('-m','pip','download','--no-deps','--require-hashes','--dest',$wheels,$driverUrl)
} finally { Pop-Location }
$redist = Get-ChildItem 'C:\BuildTools\VC\Redist\MSVC\*\x64\Microsoft.VC*.CRT' -Directory | Sort-Object FullName | Select-Object -Last 1
if (!$redist) { throw 'MSVC x64 runtime is missing.' }
Invoke-Checked $python @(
    (Join-Path $source 'tools\build_windows_product.py'),
    '--runtime',(Join-Path $Root 'python.tar.gz'),
    '--native',(Join-Path $frontend 'build\windows\x64\runner\Release'),
    '--wheels',$wheels,
    '--defaults',(Join-Path $Root 'defaults'),
    '--output',$Output,
    '--vc-runtime',$redist.FullName,
    '--source-manifest',$SourceManifest
)
$product = Join-Path $Output 'CulsmaOS'
$packaged = Join-Path $product 'runtime\python.exe'
Invoke-Checked $packaged @('-I',(Join-Path $PSScriptRoot 'smoke_product.py'),$product)
# Install pytest into the build host environment. Run against installed product
# dependencies by adding pytest via a separate target outside the archive.
$testDependencies = "$Output.tests"
Invoke-Checked $packaged @('-I','-m','pip','install','--target',$testDependencies,'pytest==8.4.2')
Push-Location $source
try {
    Invoke-Checked $packaged @('-I','-c',
        "import sys; sys.path.append(sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main())",
        $testDependencies,'-q','tests/modules/remote_access','tests/modules/lifecycle_manager/test_station_service.py',
        'tests/modules/lifecycle_manager/test_run_cancellation.py',
        'tests/modules/file_system/test_windows_host.py')
} finally { Pop-Location }
# The matching release source archive supplies only the tests and their fixtures.
$qa = "$Output.driver-qa"
New-Item -ItemType Directory -Path $qa | Out-Null
$qaArchive = Join-Path $qa 'tests.tar.gz'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/culsma/culsma-driver-hamilton/releases/download/v0.1.2/culsma_driver_hamilton-0.1.2.tar.gz' -OutFile $qaArchive
if ((Get-FileHash $qaArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'ea987d711335e51b9a2ce9cb4e7d2a7f0a317ab5413493015fc921bfb7eeb913') {
    throw 'Hamilton test source archive checksum mismatch.'
}
Invoke-Checked $python @('-I','-c',
    "import sys, tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter='data')",$qaArchive,$qa)
Push-Location (Join-Path $qa 'culsma_driver_hamilton-0.1.2')
try {
    Invoke-Checked $packaged @('-I','-c',
        "import os, sys; sys.path.extend([sys.argv.pop(1), os.getcwd()]); import pytest; raise SystemExit(pytest.main())",
        $testDependencies,'-q','tests/test_station_sdk_records.py','tests/test_station_labware.py','tests/test_mounted_traverse.py')
} finally { Pop-Location }

$installer = Join-Path $Output 'Install.ps1'
$testInstall = Join-Path $Root ('qa\' + [guid]::NewGuid().ToString('N').Substring(0,8))
$shortcutName = 'CulsmaOS Build Smoke'
& $installer -Destination $testInstall -ShortcutName $shortcutName
& $installer -Destination $testInstall -ShortcutName $shortcutName
if (!(Get-ChildItem "$testInstall.previous-*" -Directory)) {
    throw 'Full package upgrade did not retain the previous installation.'
}
