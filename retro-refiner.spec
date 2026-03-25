# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Retro-Refiner v2 — single executable with pywebview GUI."""

import os

a = Analysis(
    ['retro_refiner/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('data/systems.json', 'data'),
        ('data/title_mappings.json', 'data'),
        ('retro_refiner/ui/assets', 'retro_refiner/ui/assets'),
    ],
    hiddenimports=[
        # Core stdlib
        'os', 're', 'sys', 'signal', 'shutil', 'zipfile', 'binascii', 'fnmatch',
        'json', 'unicodedata', 'urllib.request', 'urllib.error', 'urllib.parse',
        'socket', 'ssl', 'atexit', 'subprocess', 'threading', 'pathlib',
        'collections', 'dataclasses', 'typing', 'concurrent.futures',
        'time', 'argparse', 'tempfile', 'io', 'select', 'datetime',
        'xml.etree.ElementTree', 'curses', 'termios', 'tty', 'ctypes', 'msvcrt',
        'queue', 'html.parser',
        # Third-party libraries
        'webview',
        'yaml', 'httpx', 'httpcore', 'certifi', 'idna', 'sniffio', 'anyio', 'h11',
        'humanize', 'tenacity', 'orjson', 'bs4',
        # retro_refiner package
        'retro_refiner', 'retro_refiner.config', 'retro_refiner.systems',
        'retro_refiner.paths', 'retro_refiner.network', 'retro_refiner.scanner',
        'retro_refiner.dat', 'retro_refiner.filter', 'retro_refiner.mame',
        'retro_refiner.teknoparrot', 'retro_refiner.downloader',
        'retro_refiner.transfer', 'retro_refiner.ratings', 'retro_refiner.dedup',
        'retro_refiner.updater', 'retro_refiner.models', 'retro_refiner.cli',
        'retro_refiner.ui', 'retro_refiner.ui.app', 'retro_refiner.ui.api',
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
    icon='retro_refiner/ui/assets/icon.ico',
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
)
