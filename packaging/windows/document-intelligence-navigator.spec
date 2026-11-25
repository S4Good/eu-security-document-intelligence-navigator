# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

hiddenimports = (
    collect_submodules("uvicorn.logging")
    + collect_submodules("uvicorn.loops")
    + collect_submodules("uvicorn.protocols")
    + collect_submodules("uvicorn.lifespan")
    + [
        "multipart",
        "python_multipart",
        "eu_security_navigator.main",
        "eu_security_navigator.multipart_upload",
        "eu_security_navigator.search",
        "eu_security_navigator.session_store",
    ]
)

a = Analysis(
    [str(SRC_DIR / "eu_security_navigator" / "launcher.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[
        (
            str(SRC_DIR / "eu_security_navigator" / "search.html"),
            "eu_security_navigator",
        ),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "azure",
        "bs4",
        "dotenv",
        "pytest",
        "ruff",
        "tkinter",
        "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DocumentIntelligenceNavigator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DocumentIntelligenceNavigator",
)
