<#
    Create (or refresh) a "BDO Autoroute Track" shortcut on the Desktop.

    Safe to re-run, because it overwrites its own shortcut in place.
    Pass -Remove to delete it again.

    Usage:  .\install-shortcut.ps1
            .\install-shortcut.ps1 -Remove
#>

param(
    [switch]$Remove
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

if (-not (Test-Path (Join-Path $PSScriptRoot 'run.ps1'))) {
    Write-Host "run.ps1 is missing - is this the right folder?" -ForegroundColor Red
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
# -NoExit keeps the console open so the poll log stays visible and Ctrl+C works.
$shortcut.Arguments = "-NoExit -ExecutionPolicy Bypass -File `"$PSScriptRoot\run.ps1`""
$shortcut.WorkingDirectory = $PSScriptRoot
if (Test-Path $icon) { $shortcut.IconLocation = $icon }
$shortcut.Description = 'Watch the BDO auto-route and alert on Discord on arrival or a stall'
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host "Created $linkPath" -ForegroundColor Green
Write-Host "Double-click it to start monitoring. Ctrl+C in the window stops it."
