<#
    One-time setup. Finds a supported Python, offers to install one if there is
    none, creates the virtual environment, installs dependencies, and drops a
    config.toml in place.

    Usage:  .\setup.ps1
            .\setup.ps1 -Yes     accept the Python install without asking
#>

param(
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "BDO Autoroute Track - setup" -ForegroundColor Cyan
Write-Host ""

# --- locate a supported Python -------------------------------------------
# 3.11 or 3.12 only. The OCR engine publishes no wheel for 3.13, so pip would
# otherwise fail here with a wall of resolver noise.
#
# Searching by hand rather than trusting PATH, because a fresh `winget install`
# does not reach the PATH of a session that is already running, and because the
# Microsoft Store alias in WindowsApps is a stub that cannot create a venv.

function Test-SupportedPython {
    param([string]$Exe)
    if (-not $Exe) { return $false }
    if ($Exe -like "*WindowsApps*") { return $false }
    try {
        $v = (& $Exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
    } catch { return $false }
    if (-not $?) { return $false }
    return @("3.11", "3.12") -contains ($v | Out-String).Trim()
}

function Find-Python {
    # The launcher can name a version directly, which beats whatever `python`
    # happens to point at.
    $launcher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($launcher -and $launcher.Source -notlike "*WindowsApps*") {
        foreach ($want in @("-3.12", "-3.11")) {
            try { $found = (& $launcher.Source $want -c "import sys; print(sys.executable)" 2>$null) } catch { $found = $null }
            if ($found) {
                $found = ($found | Out-String).Trim()
                if (Test-SupportedPython $found) { return $found }
            }
        }
    }

    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and (Test-SupportedPython $cmd.Source)) { return $cmd.Source }
    }

    # Where the official installer and winget put it, for a session whose PATH
    # predates the install.
    $roots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python312", "$env:ProgramFiles\Python311",
        "${env:ProgramFiles(x86)}\Python312", "${env:ProgramFiles(x86)}\Python311"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($exe in Get-ChildItem -Path $root -Filter "python.exe" -Recurse -Depth 1 -ErrorAction SilentlyContinue) {
            if (Test-SupportedPython $exe.FullName) { return $exe.FullName }
        }
    }
    return $null
}

$python = Find-Python

if ($null -eq $python) {
    Write-Host "No supported Python found." -ForegroundColor Yellow
    Write-Host "This needs Python 3.11 or 3.12. The OCR engine has no wheel for 3.13."
    Write-Host ""

    if (-not (Get-Command "winget" -ErrorAction SilentlyContinue)) {
        Write-Host "winget is not available on this machine, so please install it yourself:" -ForegroundColor Red
        Write-Host "    https://www.python.org/downloads/release/python-3129/" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Tick 'Add python.exe to PATH' in the installer, then run .\setup.cmd again."
        exit 1
    }

    $answer = "y"
    if (-not $Yes) {
        $answer = Read-Host "Install Python 3.12 now with winget? [Y/n]"
        if ($answer -eq "") { $answer = "y" }
    }
    if ($answer -notmatch '^[Yy]') {
        Write-Host ""
        Write-Host "Nothing installed. When you are ready:"
        Write-Host "    winget install -e --id Python.Python.3.12" -ForegroundColor Yellow
        Write-Host "Then run .\setup.cmd again."
        exit 1
    }

    Write-Host ""
    Write-Host "Installing Python 3.12. This takes a minute or two." -ForegroundColor Cyan
    & winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Write-Host ""

    $python = Find-Python
    if ($null -eq $python) {
        Write-Host "Python was installed but this window cannot see it yet." -ForegroundColor Yellow
        Write-Host "Close this window, open a new one, and run .\setup.cmd again."
        exit 1
    }
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
