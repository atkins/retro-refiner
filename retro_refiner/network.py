"""Network operations: URL handling, HTML scraping, source scanning.

Wraps the monolith's network functions with clean APIs.
"""
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from retro_refiner.models import ProgressEvent, ScanResult


def is_url(source: str) -> bool:
    """Check if a source string is a URL."""
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().is_url(source)


def validate_source(source: str, timeout: int = 15) -> Tuple[bool, str]:
    """Validate a source path or URL is accessible.

    Returns (is_valid, message) tuple.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().validate_source(source, timeout)


def scan_network_source(url: str, systems: List[str] = None,
                        recursive: bool = True, max_depth: int = 3,
                        auth_header: str = None, scan_workers: int = 16,
                        cache_dir: Path = None, no_cache: bool = False,
                        on_progress: Callable = None) -> ScanResult:
    """Scan a network source for ROM URLs.

    Returns structured ScanResult instead of printing to stdout.
    Uses scan cache if available and fresh.

    Args:
        url: Base URL to scan.
        systems: Optional list of system codes to filter for.
        recursive: Whether to follow subdirectories.
        max_depth: Maximum directory traversal depth.
        auth_header: Optional HTTP auth header value.
        scan_workers: Number of concurrent scan workers.
        cache_dir: Directory for scan cache files.
        no_cache: If True, bypass scan cache.
        on_progress: Optional callback for progress updates.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    mod = get_module()

    # Check cache first
    if cache_dir and not no_cache:
        cached = mod.load_scan_cache(cache_dir, url)
        if cached:
            url_dict, url_sizes = cached
            if on_progress:
                total = sum(len(urls) for urls in url_dict.values())
                on_progress(ProgressEvent(
                    phase="complete",
                    message=f"Using cached scan ({total} URLs)"
                ))
            return ScanResult(url_dict=url_dict, url_sizes=url_sizes)

    # Full scan
    url_dict, url_sizes = mod.scan_network_source_urls(
        url, systems,
        recursive=recursive,
        max_depth=max_depth,
        auth_header=auth_header,
        scan_workers=scan_workers
    )

    # Save to cache
    if cache_dir and not no_cache:
        mod.save_scan_cache(cache_dir, url, dict(url_dict), url_sizes)

    return ScanResult(url_dict=dict(url_dict), url_sizes=url_sizes)


def get_ia_auth_header(access_key: str = None,
                       secret_key: str = None) -> Optional[str]:
    """Build Internet Archive authentication header."""
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().get_ia_auth_header(access_key, secret_key)


def is_archive_org_url(url: str) -> bool:
    """Check if URL is an Archive.org source."""
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().is_archive_org_url(url)
