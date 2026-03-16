"""Download operations: file downloading with progress tracking."""
from typing import Optional


def get_download_tool() -> Optional[str]:
    """Detect best available download tool.

    Returns 'aria2c', 'curl', 'urllib', or None based on availability.
    Prefers aria2c > curl > urllib.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().get_download_tool()
