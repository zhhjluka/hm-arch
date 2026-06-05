# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the HM-Arch standalone CLI executable (MEM-61)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = Path(SPECPATH).resolve().parent
ENTRYPOINT = REPO_ROOT / "packaging" / "cli_entrypoint.py"
SRC_ROOT = REPO_ROOT / "src"

hiddenimports = collect_submodules("hm_arch")

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(SRC_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="hm-arch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
