"""MAME-specific filtering: category filtering, clone selection, CHD handling."""
from pathlib import Path
from typing import Callable, Dict, List

from retro_refiner.config import Config
from retro_refiner.models import FilterResult


def filter_mame_network(urls, config, url_sizes=None, on_progress=None):
    # type: (List[str], Config, Dict[str, int], Callable) -> FilterResult
    """Filter MAME network ROM URLs.

    Args:
        urls: List of MAME ROM URLs.
        config: Configuration object.
        url_sizes: Optional dict of URL -> file size.
        on_progress: Optional callback for progress updates.

    Returns:
        FilterResult with selected/excluded MAME ROMs.
    """
    _ = urls, config, url_sizes, on_progress  # Will be wired later
    return FilterResult(system='mame')


def download_mame_data(dat_dir, version=None, on_progress=None):
    # type: (Path, str, Callable) -> tuple
    """Download MAME catver.ini and DAT files.

    Args:
        dat_dir: Directory to store downloaded files.
        version: Optional MAME version string.
        on_progress: Optional progress callback.

    Returns:
        Tuple of (catver_path, dat_path) or similar from the monolith.
    """
    _ = on_progress  # Reserved for future progress reporting
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().download_mame_data(dat_dir, version=version)
