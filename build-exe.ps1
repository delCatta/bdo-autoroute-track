<#
    Build the installer: the PyInstaller folder, then one Setup.exe around it.

    Needs the .venv from setup.cmd. Inno Setup is fetched with winget if it is
    missing, which is the only part that asks for anything.

    Usage:  .\build-exe.ps1
            .\build-exe.ps1 -FolderOnly     stop after PyInstaller, skip the installer

    Output: dist\BDO Autoroute Track\          the folder the exe runs from
            dist\BDO-Autoroute-Track-Setup-<version>.exe
#>

param(
    [switch]$FolderOnly
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No .venv found. Run .\setup.cmd first." -ForegroundColor Red
    exit 1
}

$version = (& $python -c "import sys; sys.path.insert(0, 'src'); from bdo_autoroute import __version__; print(__version__)" | Out-String).Trim()
Write-Host "Building BDO Autoroute Track $version" -ForegroundColor Cyan

# PyInstaller narrates on stderr, which Windows PowerShell 5.1 turns into a
# terminating error under Stop. Every native call below checks its exit code
# itself, so the preference is relaxed from here on.
$ErrorActionPreference = "Continue"

& $python -m pip install --quiet --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Host "Could not install PyInstaller." -ForegroundColor Red; exit 1 }

& $python -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build packaging\app.spec
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller failed." -ForegroundColor Red; exit 1 }

$folder = Join-Path $PSScriptRoot "dist\BDO Autoroute Track"
$size = [math]::Round((Get-ChildItem $folder -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host "Built $folder ($size MB)" -ForegroundColor Green

if ($FolderOnly) { exit 0 }

# --- the installer -------------------------------------------------------
function Find-Iscc {
    $onPath = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

$iscc = Find-Iscc
if ($null -eq $iscc) {
    if (-not (Get-Command "winget" -ErrorAction SilentlyContinue)) {
        Write-Host "Inno Setup is not installed and winget is unavailable." -ForegroundColor Yellow
        Write-Host "Install it from https://jrsoftware.org/isdl.php and run this again."
        exit 1
    }
    Write-Host "Installing Inno Setup with winget ..." -ForegroundColor Cyan
    & winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements
    $iscc = Find-Iscc
    if ($null -eq $iscc) {
        Write-Host "Inno Setup was installed but cannot be found. Open a new window and run this again." -ForegroundColor Yellow
        exit 1
    }
}

& $iscc /Q "/DMyAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { Write-Host "Inno Setup failed." -ForegroundColor Red; exit 1 }

$installer = Join-Path $PSScriptRoot "dist\BDO-Autoroute-Track-Setup-$version.exe"
$installerSize = [math]::Round((Get-Item $installer).Length / 1MB)
$hash = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $installer -Leaf)" | Out-File -Encoding ascii "$installer.sha256"
Write-Host ""
Write-Host "Installer: $installer ($installerSize MB)" -ForegroundColor Green
Write-Host "SHA256:    $hash"
