# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Retro-Refiner — single executable, CLI + GUI."""

a = Analysis(
    ['retro-refiner-app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('retro-refiner.py', '.'),
        ('retro-refiner-gui.py', '.'),
        ('data/systems.json', 'data'),
        ('data/title_mappings.json', 'data'),
    ],
    hiddenimports=['tkinter', '_tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='retro-refiner',
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
