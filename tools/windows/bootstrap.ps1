param([string]$Root = 'C:\CulsmaBuild')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Path $Root -Force | Out-Null
Start-Transcript -Path "$Root\bootstrap.log" -Append
function Download-Verified($Url, $File, $Hash) {
    if (!(Test-Path $File)) { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $File }
    if ((Get-FileHash $File -Algorithm SHA256).Hash.ToLower() -ne $Hash) { throw "Hash mismatch: $File" }
}
$tools = Get-Content "$Root\tool-downloads.json" -Raw | ConvertFrom-Json
Download-Verified $tools.python.url "$Root\python.tar.gz" $tools.python.sha256
if (!(Test-Path "$Root\python\python.exe")) {
    & tar.exe -xf "$Root\python.tar.gz" -C $Root
    if ($LASTEXITCODE -ne 0) { throw 'Python extraction failed' }
}
Download-Verified $tools.git.url "$Root\git.zip" $tools.git.sha256
if (!(Test-Path "$Root\git\cmd\git.exe")) { Expand-Archive "$Root\git.zip" "$Root\git" }
Download-Verified $tools.flutter.url "$Root\flutter.zip" $tools.flutter.sha256
if (!(Test-Path "$Root\flutter\bin\flutter.bat")) {
    & tar.exe -xf "$Root\flutter.zip" -C $Root
    if ($LASTEXITCODE -ne 0) { throw 'Flutter extraction failed' }
}
$env:PATH = "$Root\git\cmd;$Root\flutter\bin;$Root\python;$env:PATH"
& "$Root\git\cmd\git.exe" config --global --add safe.directory "$Root/flutter"
$installer = "$Root\vs_buildtools.exe"
if (!(Test-Path $installer)) { Invoke-WebRequest -UseBasicParsing https://aka.ms/vs/17/release/vs_buildtools.exe -OutFile $installer }
$sig = Get-AuthenticodeSignature $installer
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike '*Microsoft Corporation*') { throw 'Microsoft installer signature not valid' }
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$found = if (Test-Path $vswhere) { & $vswhere -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath }
if (!$found) {
    $install = Start-Process $installer -Wait -PassThru -ArgumentList '--quiet --wait --norestart --nocache --installPath C:\BuildTools --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --add Microsoft.VisualStudio.Component.Windows11SDK.22621'
    if ($install.ExitCode -notin @(0,3010)) { throw "Build Tools install failed: $($install.ExitCode)" }
    "VS_INSTALL_EXIT=$($install.ExitCode)"
}
& "$Root\python\python.exe" --version
& "$Root\flutter\bin\flutter.bat" config --no-analytics
& "$Root\flutter\bin\flutter.bat" doctor -v
if ($LASTEXITCODE -ne 0) { throw 'Flutter doctor failed' }
'BOOTSTRAP_COMPLETE'
Stop-Transcript
