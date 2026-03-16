"""Import helper for the legacy monolith module.

Uses importlib to import retro-refiner.py (hyphenated filename) as a module.
All wrapper modules use this to access the existing implementations.
"""
import importlib.util
import io
import sys
from pathlib import Path

_module = None


def get_module():
    """Get the imported retro-refiner module (cached)."""
    global _module  # pylint: disable=global-statement
    if _module is None:
        script_path = Path(__file__).resolve().parent.parent / 'retro-refiner.py'
        spec = importlib.util.spec_from_file_location(
            'retro_refiner_legacy', str(script_path))
        _module = importlib.util.module_from_spec(spec)
        # Suppress the module's eager initialization output
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            spec.loader.exec_module(_module)
        finally:
            sys.stdout = old_stdout
    return _module
