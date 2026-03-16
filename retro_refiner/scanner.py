"""Source scanning: discover systems and ROM files from local and network sources."""
from pathlib import Path
from typing import Callable, Dict, List, Optional

from retro_refiner.models import ProgressEvent, SystemScanInfo


def detect_system_from_path(path: str) -> Optional[str]:
    """Detect system from a URL path or folder name.

    Returns the system code string, or None if not detected.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().detect_system_from_path(path)


def scan_local_sources(source_paths: List[Path],
                       recursive: bool = False, max_depth: int = 3,
                       verbose: bool = False,
                       on_progress: Callable = None) -> Dict[str, list]:
    """Scan local directories for ROM files.

    Returns dict of system code -> list of file path strings.

    Args:
        source_paths: Directories to scan.
        recursive: Whether to scan subdirectories.
        max_depth: Maximum directory depth.
        verbose: Enable verbose detection output.
        on_progress: Optional callback for progress updates.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    mod = get_module()

    all_systems = {}
    for source_path in source_paths:
        detected = mod.scan_for_systems(
            str(source_path),
            recursive=recursive,
            max_depth=max_depth,
            verbose=verbose
        )
        for system, files in detected.items():
            if system in all_systems:
                all_systems[system].extend(files)
            else:
                all_systems[system] = list(files)
        if on_progress:
            on_progress(ProgressEvent(
                phase="scanning",
                message=f"Scanned {source_path.name}",
            ))

    return all_systems


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
