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
    hiddenimports=[
        # retro-refiner.py and retro-refiner-gui.py are loaded dynamically via
        # importlib, so PyInstaller cannot detect their dependencies automatically.
        # All stdlib modules used by both scripts must be listed here.
        'os', 're', 'sys', 'signal', 'shutil', 'zipfile', 'binascii', 'fnmatch',
        'json', 'unicodedata', 'urllib.request', 'urllib.error', 'urllib.parse',
        'socket', 'ssl', 'atexit', 'subprocess', 'threading', 'pathlib',
        'collections', 'dataclasses', 'typing', 'concurrent.futures',
        'time', 'argparse', 'tempfile', 'io', 'select', 'datetime',
        'xml.etree.ElementTree', 'curses', 'termios', 'tty', 'ctypes', 'msvcrt',
        # GUI
        'tkinter', '_tkinter', 'tkinter.ttk', 'tkinter.filedialog',
        'tkinter.messagebox', 'tkinter.simpledialog', 'queue',
    ],
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
