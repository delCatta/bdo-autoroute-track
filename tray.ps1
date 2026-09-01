<#
    Run the monitor in the background with a system tray icon.

    Usage:  .\tray.cmd
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found. Run .\setup.cmd first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $venvPython -m bdo_autoroute tray @args
exit $LASTEXITCODE
