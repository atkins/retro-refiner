#!/usr/bin/env python3
"""Retro-Refiner unified entry point — launches GUI or CLI."""
import sys
import importlib.util
from pathlib import Path


def _get_base_path():
    """Return base path (handles PyInstaller bundle)."""
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS)  # pylint: disable=protected-access
    return Path(__file__).resolve().parent


def _import_module(name, filename):
    """Import a module by filename (needed for hyphenated names)."""
    spec = importlib.util.spec_from_file_location(name, _get_base_path() / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    """Route to CLI (if args given) or GUI (if no args)."""
    if len(sys.argv) > 1:
        mod = _import_module("retro_refiner", "retro-refiner.py")
        mod.main()
    else:
        mod = _import_module("retro_refiner_gui", "retro-refiner-gui.py")
        mod.main()


if __name__ == "__main__":
    main()
