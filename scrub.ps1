<#
    Build a report you can attach to a GitHub issue.

    Collects the log with every webhook token removed, the digit-crop samples
    and your calibration. Leaves out config.toml, whole window frames, and
    every window title.

    Usage:  .\scrub.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $venvPython -m bdo_autoroute scrub @args
exit $LASTEXITCODE
