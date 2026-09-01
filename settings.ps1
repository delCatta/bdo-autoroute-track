<#
    Open the settings window: where alerts go, the Discord webhook, how much of
    the screen to send, and the main thresholds.

    Usage:  .\settings.cmd
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found. Run .\setup.cmd first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $venvPython -m bdo_autoroute settings @args
exit $LASTEXITCODE
