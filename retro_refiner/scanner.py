"""Source scanning: discover systems and ROM files from local and network sources.

Standalone implementations extracted from the monolith. Console output is
replaced by an ``on_progress`` callback and plain stderr for errors.
"""
import re
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from retro_refiner.models import ProgressEvent, ScanResult, SystemScanInfo
from retro_refiner.network import (
    check_shutdown,
    fetch_url,
    fetch_urls_parallel,
    format_size,
    format_url,
    load_scan_cache,
    parse_html_for_directories,
    parse_html_for_files_with_sizes,
    save_scan_cache,
)
from retro_refiner.systems import load_system_data


# ---------------------------------------------------------------------------
# Progress bar (simplified — no Style/Console dependency)
# ---------------------------------------------------------------------------

class ScanProgressBar:
    """Progress bar for parallel scanning operations with callback interface."""

    def __init__(self, total: int, desc: str = 'Scanning', indent: str = ''):
        self.total = total
        self.desc = desc
        self.indent = indent
        self.current = 0
        self.start_time = time.time()
        self.bar_width = 20
        self._print_bar()

    def update(self, completed: int):
        """Update progress to specific count."""
        self.current = completed
        self._print_bar()

    @staticmethod
    def _format_time(seconds):
        """Format seconds into human-readable string."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            mins, secs = divmod(int(seconds), 60)
            return f"{mins}:{secs:02d}"
        hours, remainder = divmod(int(seconds), 3600)
        mins, secs = divmod(remainder, 60)
        return f"{hours}:{mins:02d}:{secs:02d}"

    def _print_bar(self):
        elapsed = time.time() - self.start_time

        if self.total > 0:
            pct = self.current / self.total
            filled = int(self.bar_width * pct)
            bar = '#' * filled + '-' * (self.bar_width - filled)

            if self.current > 0 and elapsed > 0:
                rate = self.current / elapsed
                remaining = (self.total - self.current) / rate if rate > 0 else 0
                rate_str = f"{rate:.1f}" if rate < 100 else f"{rate:.0f}"
                eta_str = self._format_time(remaining)
                elapsed_str = self._format_time(elapsed)
                stats = f" [{elapsed_str}<{eta_str}, {rate_str}/s]"
            else:
                stats = ""

            line = (f"\r{self.indent}{self.desc}: "
                    f"|{bar}| {self.current}/{self.total}{stats}")
        else:
            line = f"\r{self.indent}{self.desc}: {self.current}"

        print(f"{line:<79}", end='', flush=True)

    def finish(self, message: str = None):
        """Finish progress bar and optionally print a completion message."""
        print('\r' + ' ' * 79 + '\r', end='', flush=True)
        if message:
            print(f"{self.indent}{message}")

    def make_callback(self):
        """Return a callback function for use with fetch_urls_parallel."""
        def callback(completed, _total):
            self.update(completed)
        return callback


# ---------------------------------------------------------------------------
# System detection from URL path
# ---------------------------------------------------------------------------

def detect_system_from_path(path: str) -> Optional[str]:
    """Detect system from a URL path or folder name.

    Handles No-Intro style names like ``GCE - Vectrex`` and simple names
    like ``vectrex``.
    """
    sysdata = load_system_data()
    path_decoded = urllib.request.unquote(path)

    for part in path_decoded.split('/'):
        part_clean = part.strip()
        if not part_clean:
            continue

        part_lower = part_clean.lower()

        if part_lower in sysdata.folder_aliases:
            return sysdata.folder_aliases[part_lower]
        if part_lower in sysdata.known_systems:
            return part_lower

        if part_lower in sysdata.dat_name_to_system:
            return sysdata.dat_name_to_system[part_lower]

        for dat_name, system in sysdata.sorted_dat_names:
            if dat_name in part_lower:
                return system

        part_normalized = re.sub(r'[^a-z0-9]', '', part_lower)
        for alias, system in sysdata.sorted_aliases:
            alias_normalized = re.sub(r'[^a-z0-9]', '', alias)
            if len(alias_normalized) >= 4 and alias_normalized in part_normalized:
                return system

    return None


# ---------------------------------------------------------------------------
# Network source scanning (full implementation)
# ---------------------------------------------------------------------------

def _log(msg: str, on_progress: Callable = None):
    """Emit a progress message via callback, or fall through to print."""
    if on_progress:
        on_progress(ProgressEvent(phase="scanning", message=msg))
    else:
        print(msg, flush=True)


def _log_error(msg: str):
    """Write an error message to stderr."""
    print(msg, file=sys.stderr, flush=True)


def scan_network_source_urls(
        base_url: str,
        systems: List[str] = None,
        recursive: bool = True,
        max_depth: int = 3,
        auth_header: Optional[str] = None,
        scan_workers: int = 16,
        on_progress: Callable = None,
        *,
        _indent: str = "",
        _url_sizes: Dict[str, int] = None,
) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
    """Scan a network source and collect ROMs (without downloading).

    Returns tuple of (dict of system -> list of URLs, dict of URL -> size).
    """
    sysdata = load_system_data()
    detected: Dict[str, List[str]] = defaultdict(list)
    if _url_sizes is None:
        _url_sizes = {}

    if not _indent:
        _log(f"Scanning network source: {format_url(base_url)}", on_progress)

    # Fetch root listing
    try:
        if not _indent:
            print("  Fetching directory listing...", end='', flush=True)
        content, final_url = fetch_url(base_url, auth_header=auth_header)
        html = content.decode('utf-8', errors='replace')
        base_url = final_url
        if not _indent:
            print(f" OK ({format_size(len(content))})")
    except Exception as exc:  # pylint: disable=broad-except
        if not _indent:
            print()
        _log_error(f"Error fetching {format_url(base_url)}: {exc}")
        return dict(detected), _url_sizes

    # Detect system from URL path
    url_system = detect_system_from_path(base_url)

    # Check for ROM files in this listing (with sizes)
    rom_files_with_sizes = parse_html_for_files_with_sizes(html, base_url)
    check_shutdown()

    if rom_files_with_sizes:
        total_size = sum(size for _, size in rom_files_with_sizes)
        if not _indent:
            size_info = f" ({format_size(total_size)})" if total_size > 0 else ""
            _log(f"  Found {len(rom_files_with_sizes)} ROM files in root{size_info}",
                 on_progress)

        ambiguous_extensions = {'.chd', '.iso', '.bin', '.cue', '.img'}
        for rom_url, size in rom_files_with_sizes:
            url_clean = rom_url.split('?')[0].split('#')[0]
            ext = ('.' + url_clean.rsplit('.', 1)[-1].lower()) if '.' in url_clean else ''
            system = sysdata.extension_to_system.get(ext)
            if ext in ambiguous_extensions and url_system:
                system = url_system
            elif not system and url_system:
                system = url_system
            elif not system:
                system = 'unknown'
            if systems is None or system in systems:
                detected[system].append(rom_url)
                if size > 0:
                    _url_sizes[rom_url] = size

    # Explore subdirectories — always scan system folders (they contain
    # the actual ROMs), but only recurse deeper when recursive is enabled
    should_explore = max_depth > 0 and (
        recursive or not rom_files_with_sizes)
    if should_explore:
        subdirs = parse_html_for_directories(html, base_url)
        if not _indent and subdirs:
            print(f"  Parsing {len(subdirs)} entries...", end='', flush=True)

        system_subdirs: list = []
        other_subdirs: list = []

        for subdir_url in subdirs:
            folder_name = urllib.request.unquote(subdir_url.rstrip('/').split('/')[-1])
            folder_lower = folder_name.lower()
            system = sysdata.folder_aliases.get(folder_lower, folder_lower)
            is_system_folder = system in sysdata.known_systems

            # Fall back to detect_system_from_path for No-Intro style
            # names like "Sega - Mega Drive - Genesis"
            if not is_system_folder:
                detected_sys = detect_system_from_path(folder_name)
                if detected_sys:
                    system = detected_sys
                    is_system_folder = True

            if is_system_folder:
                if systems and system not in systems:
                    continue
                system_subdirs.append((subdir_url, system, folder_name))
            elif recursive and max_depth > 1 and not rom_files_with_sizes:
                other_subdirs.append((subdir_url, folder_name))

        # Parallel fetch system subdirectories
        if system_subdirs:
            urls_to_fetch = [u for u, _, _ in system_subdirs]
            url_to_info = {u: (s, fn) for u, s, fn in system_subdirs}

            if len(urls_to_fetch) > 1:
                progress = ScanProgressBar(
                    total=len(urls_to_fetch),
                    desc=f"Scanning {len(urls_to_fetch)} system folders",
                    indent=f"{_indent}  "
                )

                def _scan_progress(completed, _total):
                    progress.update(completed)
                    if on_progress:
                        on_progress(ProgressEvent(
                            phase="scanning",
                            message=(f"Scanning system folders: "
                                     f"{completed}/{len(urls_to_fetch)}"),
                            current=completed,
                            total=len(urls_to_fetch),
                        ))

                fetched = fetch_urls_parallel(
                    urls_to_fetch,
                    max_workers=scan_workers,
                    auth_header=auth_header,
                    progress_callback=_scan_progress,
                )
                progress.finish()
            else:
                fetched = {}
                for fetch_target in urls_to_fetch:
                    try:
                        cnt, final = fetch_url(fetch_target, auth_header=auth_header)
                        fetched[fetch_target] = (cnt, final)
                    except Exception:  # pylint: disable=broad-except
                        pass

            for subdir_url in urls_to_fetch:
                check_shutdown()
                if subdir_url not in fetched:
                    continue

                system, folder_name = url_to_info[subdir_url]
                sub_content, sub_final_url = fetched[subdir_url]
                subdir_html = sub_content.decode('utf-8', errors='replace')
                sub_files_with_sizes = parse_html_for_files_with_sizes(subdir_html, sub_final_url)

                if sub_files_with_sizes:
                    sub_rom_urls = [u for u, _ in sub_files_with_sizes]
                    total_size = sum(s for _, s in sub_files_with_sizes)
                    size_info = f" ({format_size(total_size)})" if total_size > 0 else ""
                    _log(f"{_indent}    {folder_name} ({system}): "
                         f"{len(sub_rom_urls)} ROMs{size_info}",
                         on_progress)
                    detected[system].extend(sub_rom_urls)
                    for rom_url, size in sub_files_with_sizes:
                        if size > 0:
                            _url_sizes[rom_url] = size

                # Nested subdirectories (region folders, etc.)
                if recursive and max_depth > 1:
                    nested_subdirs = parse_html_for_directories(subdir_html, sub_final_url)
                    if nested_subdirs:
                        nested_fetched = fetch_urls_parallel(
                            nested_subdirs,
                            max_workers=scan_workers,
                            auth_header=auth_header
                        )
                        for nested_url, (nested_content, nested_final) in nested_fetched.items():
                            check_shutdown()
                            nested_html = nested_content.decode('utf-8', errors='replace')
                            nested_files = parse_html_for_files_with_sizes(
                                nested_html, nested_final)
                            if nested_files:
                                nested_name = urllib.request.unquote(
                                    nested_url.rstrip('/').split('/')[-1])
                                nested_roms = [u for u, _ in nested_files]
                                nested_size = sum(s for _, s in nested_files)
                                size_info = (f" ({format_size(nested_size)})"
                                             if nested_size > 0 else "")
                                _log(f"{_indent}      Found {len(nested_roms)} "
                                     f"ROMs in {nested_name}{size_info}",
                                     on_progress)
                                detected[system].extend(nested_roms)
                                for rom_url, size in nested_files:
                                    if size > 0:
                                        _url_sizes[rom_url] = size

        if not _indent and subdirs:
            total_found = len(system_subdirs) + len(other_subdirs)
            parts = []
            if system_subdirs:
                parts.append(f"{len(system_subdirs)} system folders")
            if other_subdirs:
                parts.append(f"{len(other_subdirs)} game folders")
            print(f" {total_found} found ({', '.join(parts)})" if parts else " 0 found")

        if not _indent and not system_subdirs and not other_subdirs and not rom_files_with_sizes:
            _log("  No ROM files or subdirectories found", on_progress)

        # Non-system subdirectories
        if other_subdirs:
            if url_system and (systems is None or url_system in systems):
                urls_to_fetch = [u for u, _ in other_subdirs]

                if len(urls_to_fetch) > 3:
                    progress = ScanProgressBar(
                        total=len(urls_to_fetch),
                        desc=f"Scanning {len(urls_to_fetch)} game folders",
                        indent=f"{_indent}  "
                    )
                    fetched = fetch_urls_parallel(
                        urls_to_fetch,
                        max_workers=scan_workers,
                        auth_header=auth_header,
                        progress_callback=progress.make_callback()
                    )
                    progress.finish(
                        f"Scanned {len(fetched)}/{len(urls_to_fetch)} folders")
                else:
                    fetched = {}
                    for fetch_target in urls_to_fetch:
                        try:
                            cnt, final = fetch_url(fetch_target, auth_header=auth_header)
                            fetched[fetch_target] = (cnt, final)
                        except Exception:  # pylint: disable=broad-except
                            pass

                total_roms = 0
                total_size = 0
                nested_urls_to_fetch: list = []
                for subdir_url, (sub_content, sub_final_url) in fetched.items():
                    check_shutdown()
                    subdir_html = sub_content.decode('utf-8', errors='replace')
                    sub_files = parse_html_for_files_with_sizes(subdir_html, sub_final_url)
                    if sub_files:
                        for rom_url, size in sub_files:
                            detected[url_system].append(rom_url)
                            if size > 0:
                                _url_sizes[rom_url] = size
                                total_size += size
                        total_roms += len(sub_files)
                    nested_dirs = parse_html_for_directories(subdir_html, sub_final_url)
                    if nested_dirs:
                        nested_urls_to_fetch.extend(nested_dirs)

                if nested_urls_to_fetch:
                    if len(nested_urls_to_fetch) > 3:
                        nested_progress = ScanProgressBar(
                            total=len(nested_urls_to_fetch),
                            desc=f"Scanning {len(nested_urls_to_fetch)} nested folders",
                            indent=f"{_indent}  "
                        )
                        nested_fetched = fetch_urls_parallel(
                            nested_urls_to_fetch,
                            max_workers=scan_workers,
                            auth_header=auth_header,
                            progress_callback=nested_progress.make_callback()
                        )
                        nested_progress.finish(
                            f"Scanned {len(nested_fetched)}/"
                            f"{len(nested_urls_to_fetch)} nested folders"
                        )
                    else:
                        nested_fetched = {}
                        for nurl in nested_urls_to_fetch:
                            try:
                                ncontent, nfinal = fetch_url(nurl, auth_header=auth_header)
                                nested_fetched[nurl] = (ncontent, nfinal)
                            except Exception:  # pylint: disable=broad-except
                                pass

                    for _nested_url, (ncontent, nfinal_url) in nested_fetched.items():
                        check_shutdown()
                        nested_html = ncontent.decode('utf-8', errors='replace')
                        nested_files = parse_html_for_files_with_sizes(
                            nested_html, nfinal_url)
                        if nested_files:
                            for rom_url, size in nested_files:
                                detected[url_system].append(rom_url)
                                if size > 0:
                                    _url_sizes[rom_url] = size
                                    total_size += size
                            total_roms += len(nested_files)

                if total_roms > 0:
                    size_info = f" ({format_size(total_size)})" if total_size > 0 else ""
                    _log(f"{_indent}  Found {total_roms} ROMs{size_info}",
                         on_progress)

            else:
                # No URL system detected — scan recursively (sequentially)
                for subdir_url, folder_name in other_subdirs:
                    check_shutdown()
                    _log(f"{_indent}  Scanning subfolder: {folder_name}...",
                         on_progress)
                    sub_detected, _ = scan_network_source_urls(
                        subdir_url, systems,
                        recursive=True, max_depth=max_depth - 1,
                        auth_header=auth_header,
                        scan_workers=scan_workers,
                        on_progress=on_progress,
                        _indent=_indent + "  ",
                        _url_sizes=_url_sizes,
                    )
                    for sys_code, url_list in sub_detected.items():
                        detected[sys_code].extend(url_list)

    return dict(detected), _url_sizes


# ---------------------------------------------------------------------------
# High-level scan_network_source (public API)
# ---------------------------------------------------------------------------

def scan_network_source(url: str, systems: List[str] = None,
                        recursive: bool = True, max_depth: int = 3,
                        auth_header: str = None, scan_workers: int = 16,
                        cache_dir: Path = None, no_cache: bool = False,
                        on_progress: Callable = None) -> ScanResult:
    """Scan a network source for ROMs.

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
    # Check cache first
    if cache_dir and not no_cache:
        cached = load_scan_cache(cache_dir, url)
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
    url_dict, url_sizes = scan_network_source_urls(
        url, systems,
        recursive=recursive,
        max_depth=max_depth,
        auth_header=auth_header,
        scan_workers=scan_workers,
        on_progress=on_progress,
    )

    # Save to cache
    if cache_dir and not no_cache:
        save_scan_cache(cache_dir, url, dict(url_dict), url_sizes)

    return ScanResult(url_dict=dict(url_dict), url_sizes=url_sizes)


# ---------------------------------------------------------------------------
# Local source scanning (standalone implementation)
# ---------------------------------------------------------------------------

def _detect_system_from_folder(folder_name: str) -> str:
    """Normalize folder name to standard system name."""
    sysdata = load_system_data()
    name = folder_name.lower().strip()
    if name in sysdata.folder_aliases:
        return sysdata.folder_aliases[name]
    return name


def _detect_system_from_extension(filename: str) -> Optional[str]:
    """Detect system type from file extension."""
    sysdata = load_system_data()
    ext = Path(filename).suffix.lower()
    if ext in sysdata.extension_to_system:
        return sysdata.extension_to_system[ext]

    # For archives, check inner extension (e.g., "Game.nes.zip")
    if ext in ('.zip', '.7z', '.rar'):
        name_without_archive = filename[:-len(ext)]
        inner_match = re.search(
            r'\.([a-z0-9]{2,4})$', name_without_archive, re.IGNORECASE
        )
        if inner_match:
            inner_ext = '.' + inner_match.group(1).lower()
            if inner_ext in sysdata.extension_to_system:
                return sysdata.extension_to_system[inner_ext]

    return None


def scan_local_sources(source_paths: List[Path],
                       recursive: bool = False, max_depth: int = 3,
                       verbose: bool = False,
                       on_progress: Callable = None) -> Dict[str, list]:
    """Scan local directories for ROM files.

    Returns dict of system code -> list of Path objects.

    Args:
        source_paths: Directories to scan.
        recursive: Whether to scan subdirectories.
        max_depth: Maximum directory depth.
        verbose: Enable verbose detection output.
        on_progress: Optional callback for progress updates.
    """
    sysdata = load_system_data()

    # Build ROM extensions from loaded system data + archive/generic formats
    archive_formats = {'.zip', '.7z', '.rar'}
    generic_formats = {
        '.iso', '.bin', '.cue', '.chd', '.wad', '.dol',
        '.tgc', '.vpk', '.pkg'
    }
    rom_extensions = (
        set(sysdata.extension_to_system.keys())
        | archive_formats
        | generic_formats
    )

    all_systems: Dict[str, list] = defaultdict(list)

    def _scan_directory(dir_path: Path, current_depth: int,
                        parent_system: str = None):
        """Recursively scan a directory for ROMs."""
        if current_depth > max_depth:
            return

        try:
            entries = list(dir_path.iterdir())
        except PermissionError:
            if verbose:
                _log(f"  [SKIP] Permission denied: {dir_path}", on_progress)
            return

        # Check if this directory name is a known system
        folder_system = _detect_system_from_folder(dir_path.name)
        is_system_folder = folder_system in sysdata.known_systems
        active_system = folder_system if is_system_folder else parent_system

        if verbose and is_system_folder:
            _log(
                f"  [DETECT] Folder '{dir_path.name}'"
                f" -> system '{folder_system}'",
                on_progress
            )

        # Collect ROMs in this directory
        for entry in entries:
            if entry.is_file() and entry.suffix.lower() in rom_extensions:
                if active_system:
                    all_systems[active_system].append(entry)
                else:
                    detected = _detect_system_from_extension(entry.name)
                    if detected:
                        all_systems[detected].append(entry)
                        if verbose:
                            _log(
                                f"  [DETECT] Extension '{entry.suffix}'"
                                f" -> system '{detected}': {entry.name}",
                                on_progress
                            )
                    elif verbose:
                        _log(
                            f"  [SKIP] Unrecognized extension:"
                            f" {entry.name}",
                            on_progress
                        )

        # Recurse into subdirectories if enabled
        if recursive:
            for entry in entries:
                if (entry.is_dir()
                        and not entry.name.startswith('_')
                        and not entry.name.startswith('.')):
                    _scan_directory(entry, current_depth + 1, active_system)

    for source_path in source_paths:
        _scan_directory(source_path, 0, None)
        if on_progress:
            on_progress(ProgressEvent(
                phase="scanning",
                message=f"Scanned {source_path.name}",
            ))

    return dict(all_systems)


def get_system_scan_info(systems_dict: Dict[str, list],
                         source_type: str = "local") -> List[SystemScanInfo]:
    """Convert a scan result dict into SystemScanInfo objects.

    Args:
        systems_dict: Dict of system -> list of file paths or URLs.
        source_type: 'local' or 'network'.
    """
    results = []
    for system, files in sorted(systems_dict.items()):
        total_size = 0
        if source_type == "local":
            for filepath in files:
                try:
                    total_size += Path(filepath).stat().st_size
                except OSError:
                    pass
        results.append(SystemScanInfo(
            system=system,
            file_count=len(files),
            total_size=total_size,
            source_type=source_type,
        ))
    return results
