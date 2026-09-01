<#
    One-time setup: create the virtual environment, install dependencies,
    and drop a config.toml in place.

    Usage:  .\setup.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "BDO barter boat monitor - setup" -ForegroundColor Cyan
Write-Host ""

# --- locate a real Python ------------------------------------------------
# The Microsoft Store alias in WindowsApps is a stub that cannot create venvs,
# so it is filtered out explicitly.
$python = $null
foreach ($candidate in @("py", "python", "python3")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { continue }
    if ($cmd.Source -like "*WindowsApps*") { continue }
    $python = $cmd.Source
    break
}

if ($null -eq $python) {
    Write-Host "No usable Python found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install it with:"
    Write-Host "    winget install -e --id Python.Python.3.12" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Then open a NEW terminal and run .\setup.ps1 again."
    exit 1
}

Write-Host "Using Python at $python"
& $python --version

# --- create the venv -----------------------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment in .venv ..."
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "venv creation failed." -ForegroundColor Red; exit 1 }
} else {
    Write-Host ".venv already exists, reusing it."
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Expected $venvPython but it is missing." -ForegroundColor Red
    exit 1
}

# --- install dependencies ------------------------------------------------
Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "pip upgrade failed." -ForegroundColor Red; exit 1 }

Write-Host "Installing dependencies (the OCR model is ~15 MB, this takes a minute) ..."
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Dependency install failed." -ForegroundColor Red; exit 1 }

# --- seed the config -----------------------------------------------------
if (-not (Test-Path "config.toml")) {
    Copy-Item "config.example.toml" "config.toml"
    Write-Host "Created config.toml from the example." -ForegroundColor Green
} else {
    Write-Host "config.toml already exists, leaving it alone."
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Put your Discord webhook URL in config.toml (notify.discord_webhook_url)."
Write-Host "  2. Set Black Desert to Borderless Windowed, and start an auto-route so the"
Write-Host "     remaining-distance number is on screen."
Write-Host "  3. Run  .\calibrate.ps1   and drag a box around that number."
Write-Host "  4. Run  .\run.ps1         to start monitoring."
