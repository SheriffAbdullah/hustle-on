# -*- mode: python ; coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.abspath(SPECPATH))
import make_version_info
make_version_info.generate(os.path.abspath(SPECPATH))  # _version.py + version_info.txt


a = Analysis(
    ['hustleon_tray.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name='hustle-on',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest='app.manifest',
    version='version_info.txt',
)
