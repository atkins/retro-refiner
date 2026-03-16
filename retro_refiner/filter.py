"""ROM filtering: select best ROMs from a collection."""
from typing import Callable, Dict, List

from retro_refiner.config import Config
from retro_refiner.models import FilterResult


def filter_console_roms(system, rom_files, config, dat_entries=None,
                        on_progress=None):
    # type: (str, list, Config, dict, Callable) -> FilterResult
    """Filter console ROMs for a system using the v1 engine.

    Wraps the monolith's filter_roms_from_files with structured results.

    Args:
        system: System code (e.g. 'snes').
        rom_files: List of ROM file paths or URLs.
        config: Configuration object.
        dat_entries: Optional pre-loaded DAT entries dict.
        on_progress: Optional callback for progress updates.

    Returns:
        FilterResult with selected/excluded ROMs and statistics.
    """
    _ = rom_files, config, dat_entries, on_progress  # Will be wired later
    return FilterResult(system=system)


def filter_network_roms(system, urls, config, url_sizes=None,
                        dat_entries=None, on_progress=None):
    # type: (str, List[str], Config, Dict[str, int], dict, Callable) -> FilterResult
    """Filter network ROM URLs for a console system.

    Wraps the monolith's network ROM filtering with structured results.

    Args:
        system: System code.
        urls: List of ROM URLs.
        config: Configuration object.
        url_sizes: Optional dict of URL -> file size.
        dat_entries: Optional pre-loaded DAT entries dict.
        on_progress: Optional callback for progress updates.

    Returns:
        FilterResult with selected/excluded URLs and statistics.
    """
    _ = urls, config, url_sizes, dat_entries, on_progress  # Will be wired later
    return FilterResult(system=system)
