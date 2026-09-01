<#
    Pick the region of the screen holding the remaining-distance number.
    Run this once, and again whenever you change resolution or UI scale.

    Usage:  .\calibrate.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "Make sure Black Desert is running an auto-route so the distance number" -ForegroundColor Cyan
Write-Host "is visible on screen right now." -ForegroundColor Cyan
Write-Host ""

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $venvPython -m bdo_tracker calibrate @args
exit $LASTEXITCODE
