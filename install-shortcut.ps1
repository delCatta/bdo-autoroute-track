<#
    Create (or refresh) a "BDO Autoroute Track" shortcut on the Desktop.

    Starts the tray by default: an icon in the notification area, no window in
    the way. Pass -Console for the old behaviour, a PowerShell window with the
    poll log scrolling past, which is what you want when something is wrong.

    Safe to re-run, because it overwrites its own shortcut in place.

    Usage:  .\install-shortcut.ps1
            .\install-shortcut.ps1 -Console
            .\install-shortcut.ps1 -Remove
#>

param(
    [switch]$Remove,
    [switch]$Console
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# GetFolderPath, not $env:USERPROFILE\Desktop, because it follows OneDrive redirection.
$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop 'BDO Autoroute Track.lnk'

if ($Remove) {
    if (Test-Path $linkPath) {
        Remove-Item $linkPath -Force
        Write-Host "Removed $linkPath" -ForegroundColor Green
    } else {
        Write-Host "Nothing to remove; no shortcut at $linkPath"
    }
    exit 0
}

$script = if ($Console) { 'run.ps1' } else { 'tray.ps1' }
if (-not (Test-Path (Join-Path $PSScriptRoot $script))) {
    Write-Host "$script is missing. Is this the right folder?" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $PSScriptRoot '.venv'))) {
    Write-Host "No .venv yet. Run .\setup.ps1 first, then this." -ForegroundColor Yellow
}

$icon = Join-Path $PSScriptRoot 'assets\boat.ico'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $powershell

if ($Console) {
    # -NoExit keeps the console open so the poll log stays visible and Ctrl+C works.
    $shortcut.Arguments = "-NoExit -ExecutionPolicy Bypass -File `"$PSScriptRoot\run.ps1`""
    $shortcut.WindowStyle = 1
    $shortcut.Description = 'Watch the BDO auto-route in a console window'
} else {
    # Hidden, because the tray icon is the interface. tray.ps1 runs pythonw, so
    # nothing of its own appears either. It cannot go straight to pythonw.exe:
    # the package is on PYTHONPATH rather than installed, and a shortcut has no
    # way to set an environment variable.
    $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\tray.ps1`""
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Watch the BDO auto-route from the system tray'
}

$shortcut.WorkingDirectory = $PSScriptRoot
if (Test-Path $icon) { $shortcut.IconLocation = $icon }
$shortcut.Save()

Write-Host "Created $linkPath" -ForegroundColor Green
if ($Console) {
    Write-Host "Double-click it to start monitoring. Ctrl+C in the window stops it."
} else {
    Write-Host "Double-click it and look for the boat in the notification area."
    Write-Host "Right-click the icon for settings, per-channel switches, and Quit."
    Write-Host ""
    Write-Host "Want the console log instead? .\install-shortcut.cmd -Console"
}
