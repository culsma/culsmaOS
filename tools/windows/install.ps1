param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\CulsmaOS-Remote-Preview'),
    [string]$ShortcutName = 'CulsmaOS Remote Preview',
    [switch]$RestoreRemoteAccess,
    [switch]$Start
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'CulsmaOS'
$state = Join-Path $env:LOCALAPPDATA 'CulsmaOS\windows-preview'
$Destination = [IO.Path]::GetFullPath($Destination)
$staged = Join-Path (Split-Path $Destination) ('.cin-' + [guid]::NewGuid().ToString('N').Substring(0,12))
$backup = "$Destination.previous-$([guid]::NewGuid().ToString('N'))"
if ($ShortcutName -notmatch '^[a-zA-Z0-9 ._-]+$') { throw 'Invalid shortcut name.' }
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (!$desktop) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }
New-Item -ItemType Directory -Force -Path $desktop | Out-Null
if (Test-Path -LiteralPath $Destination) {
    if (!(Test-Path -LiteralPath (Join-Path $Destination 'Product.json'))) { throw 'Destination is not an installed CulsmaOS product.' }
}
function Get-ProductProcesses {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Destination + '\', [StringComparison]::OrdinalIgnoreCase)
    })
}
$marker = Join-Path $state 'remote-pairings\enabled'
if ($RestoreRemoteAccess -and !(Get-ChildItem (Split-Path $marker) -Filter '*.json' -ErrorAction SilentlyContinue)) {
    throw 'Remote access can only be restored for a station with an existing pairing.'
}
New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
try {
    # Robocopy supports long paths in the embedded Python distribution.
    & robocopy.exe $source $staged /E /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "Could not stage the complete product ($LASTEXITCODE)." }
    $python = Join-Path $staged 'runtime\python.exe'
    & $python -I -c "from culsma_os.console.adapters.mcp import MCPServerAdapter; from culsma_driver_hamilton.venus.initialization.interactors import VenusInitializationInteractor; from culsma_hamilton_os.providers import HamiltonOSDeviceFactory; assert hasattr(MCPServerAdapter, 'initialize_station') and hasattr(HamiltonOSDeviceFactory, 'build_station_service')"
    if ($LASTEXITCODE -ne 0) { throw 'Packaged initialization components failed verification.' }
    & $python -I -c "from culsma_driver_hamilton.labware_profiles.catalogue import LabwareProfiles; p=LabwareProfiles(); assert all(p.read(p.path(i)) for i in p.records)"
    if ($LASTEXITCODE -ne 0) { throw 'Packaged labware geometry failed verification.' }
    $processes = @(Get-ProductProcesses)
    # Identify the desktop by its entry point. The resident also uses pythonw.
    if ($processes | Where-Object { $_.Name -eq 'culsma_console.exe' -or $_.CommandLine -match 'launch\.py"?\s+desktop\s*$' }) {
        throw 'Close the CulsmaOS desktop window before upgrading.'
    }
    $previousAgent = @($processes | Where-Object { $_.CommandLine -match 'launch\.py"?\s+agent\s*$' })
    if (Test-Path -LiteralPath $Destination) {
        $check = @((Join-Path $staged 'prepare_upgrade.py'), $state)
        & $python -I @check
        if ($LASTEXITCODE -ne 0) { throw 'The station must be idle and all device operations settled before upgrading.' }
    }
    if ($previousAgent) {
        Stop-Process -Id $previousAgent.ProcessId
    }
    for ($i = 0; $i -lt 20 -and (Get-ProductProcesses); $i++) { Start-Sleep -Milliseconds 250 }
    if (Get-ProductProcesses) { throw 'The previous CulsmaOS processes have not exited.' }

    if (Test-Path -LiteralPath $Destination) { Move-Item -LiteralPath $Destination -Destination $backup }
    try {
        Move-Item -LiteralPath $staged -Destination $Destination
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop ($ShortcutName + '.lnk')))
        $shortcut.TargetPath = Join-Path $Destination 'runtime\pythonw.exe'
        $shortcut.Arguments = '-X utf8 -I "' + (Join-Path $Destination 'launch.py') + '" desktop'
        $shortcut.WorkingDirectory = $Destination
        $shortcut.IconLocation = (Join-Path $Destination 'Native\culsma_console.exe') + ',0'
        $shortcut.Save()
        if ($RestoreRemoteAccess -and !(Test-Path -LiteralPath $marker)) {
            New-Item -ItemType File -Path $marker | Out-Null
        }
    } catch {
        if (Test-Path -LiteralPath $Destination) { Move-Item -LiteralPath $Destination -Destination $staged }
        if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $Destination }
        throw
    }
    if (Test-Path -LiteralPath $backup) { Write-Host "Previous installation saved at $backup" }
    if ($Start) { Start-Process -FilePath $shortcut.TargetPath -ArgumentList $shortcut.Arguments -WorkingDirectory $Destination }
    Write-Host 'CulsmaOS installed. The product and station state are stored separately.'
} finally {
    if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Recurse -Force }
}
