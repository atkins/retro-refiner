"""Path resolution helpers for bundled data and writable runtime files.

In development: both paths resolve to the project root directory.
In PyInstaller builds: base_path is sys._MEIPASS (read-only bundled data),
runtime_path is the directory containing the executable (writable).
"""
import sys
from pathlib import Path


def get_base_path() -> Path:
    """Get path to bundled read-only data (data/*.json).

    Returns sys._MEIPASS in PyInstaller builds, otherwise the project root.
    """
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS)  # pylint: disable=protected-access
    return Path(__file__).resolve().parent.parent


def get_runtime_path() -> Path:
    """Get path for writable runtime files (dat_files/, cache/, logs).

    Returns the executable's directory in PyInstaller builds,
    otherwise the project root.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent
