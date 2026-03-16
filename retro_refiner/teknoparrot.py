"""TeknoParrot-specific filtering: version dedup, platform filtering."""
from typing import Callable, Dict, List

from retro_refiner.config import Config
from retro_refiner.models import FilterResult


def filter_teknoparrot_network(urls, config, url_sizes=None,
                               on_progress=None):
    # type: (List[str], Config, Dict[str, int], Callable) -> FilterResult
    """Filter TeknoParrot network ROM URLs.

    Args:
        urls: List of TeknoParrot ROM URLs.
        config: Configuration object.
        url_sizes: Optional dict of URL -> file size.
        on_progress: Optional callback for progress updates.

    Returns:
        FilterResult with selected/excluded TeknoParrot ROMs.
    """
    _ = urls, config, url_sizes, on_progress  # Will be wired later
    return FilterResult(system='teknoparrot')
