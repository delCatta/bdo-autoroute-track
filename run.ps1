<#
    Start monitoring. Any extra arguments are forwarded to the CLI.

    Usage:  .\run.ps1
            .\run.ps1 --once      # single poll, useful for a quick check
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $venvPython -m bdo_autoroute run @args
exit $LASTEXITCODE
