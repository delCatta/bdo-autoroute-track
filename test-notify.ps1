<#
    Send one test alert to the configured Discord webhook.

    Usage:  .\test-notify.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $venvPython -m bdo_tracker test-notify @args
exit $LASTEXITCODE
