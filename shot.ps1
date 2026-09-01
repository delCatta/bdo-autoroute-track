<#
    Save a frame plus the calibrated crop into captures\ for troubleshooting.

    Usage:  .\shot.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $venvPython -m bdo_autoroute shot @args
exit $LASTEXITCODE
