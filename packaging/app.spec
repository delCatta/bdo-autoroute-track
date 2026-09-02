# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the windowed exe.

One folder, not one file. A single-file exe unpacks ~250MB into %TEMP% on
every launch, which is slow and exactly the behaviour antivirus dislikes. The
folder is hidden behind the installer, so nobody has to look at it.

Build with build-exe.cmd, which also runs the installer script.
"""

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
NAME = "BDO Autoroute Track"

VERSION = re.search(
    r'__version__ = "([^"]+)"', (ROOT / "src" / "bdo_autoroute" / "__init__.py").read_text()
).group(1)
NUMBERS = tuple(int(part) for part in VERSION.split(".")[:3]) + (0,)

datas = [
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "config.example.toml"), "."),
]
binaries = []
hiddenimports = []

# Both ship files pip installs beside the code: the OCR models and their
# config, and the widget theme. PyInstaller only follows imports.
for package in ("rapidocr_onnxruntime", "customtkinter"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
binaries += collect_dynamic_libs("onnxruntime")

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=NUMBERS, prodvers=NUMBERS),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("ProductName", NAME),
                        StringStruct("FileDescription", NAME),
                        StringStruct("ProductVersion", VERSION),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("CompanyName", "delCatta"),
                        StringStruct("LegalCopyright", "MIT licensed. Not affiliated with Pearl Abyss."),
                        StringStruct("OriginalFilename", f"{NAME}.exe"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "pip", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    icon=str(ROOT / "assets" / "boat.ico"),
    version=version_info,
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)
