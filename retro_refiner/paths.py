"""Path resolution helpers for bundled data and writable runtime files.

In development: both paths resolve to the project root directory.
In PyInstaller builds: base_path is sys._MEIPASS (read-only bundled data),
runtime_path is the directory containing the executable (writable).
In Nuitka builds: both paths resolve relative to the compiled module location.
"""
import sys
from pathlib import Path


def is_bundled() -> bool:
    """Return True if running as a bundled executable (PyInstaller or Nuitka)."""
    if getattr(sys, 'frozen', False):
        return True
    # Nuitka standalone: __compiled__ is set on compiled modules
    try:
        return bool(__compiled__)  # type: ignore[name-defined]  # noqa: F821
    except NameError:
        return False


def get_base_path() -> Path:
    """Get path to bundled read-only data (data/*.json).

    PyInstaller: sys._MEIPASS (temp extraction directory).
    Nuitka: relative to compiled module (directory structure preserved).
    Development: project root.
    """
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS)  # pylint: disable=protected-access
    return Path(__file__).resolve().parent.parent


def get_runtime_path() -> Path:
    """Get path for writable runtime files (dat_files/, cache/, logs).

    Returns the executable's directory in bundled builds,
    otherwise the project root.
    """
    if is_bundled():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent
