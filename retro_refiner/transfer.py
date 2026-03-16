"""File transfer: copy/move/symlink/hardlink ROM files to destination."""
from pathlib import Path
from typing import Callable


def transfer_files(files, dest_dir, mode='copy', flat=False, system=None,
                   on_progress=None):
    # type: (list, Path, str, bool, str, Callable) -> dict
    """Transfer ROM files to destination directory.

    Args:
        files: List of file paths to transfer.
        dest_dir: Destination directory.
        mode: Transfer mode - 'copy', 'move', 'link', or 'hardlink'.
        flat: If True, place all files in dest_dir without subdirectories.
        system: Optional system code for subdirectory naming.
        on_progress: Optional callback for progress updates.

    Returns:
        Dict with 'transferred', 'skipped', and 'errors' counts.
    """
    _ = files, dest_dir, mode, flat, system, on_progress  # Will be wired later
    return {'transferred': 0, 'skipped': 0, 'errors': 0}
