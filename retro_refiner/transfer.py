"""File transfer: copy/move/symlink/hardlink ROM files to destination."""
import os
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional

from retro_refiner.models import ProgressEvent


def transfer_files(files: List[Path], dest_dir: Path, mode: str = 'copy',
                   flat: bool = False, system: Optional[str] = None,
                   on_progress: Optional[Callable] = None) -> Dict[str, int]:
    """Transfer ROM files to destination directory.

    Args:
        files: List of source file paths to transfer.
        dest_dir: Destination directory.
        mode: Transfer mode - 'copy', 'move', 'link' (symlink), or 'hardlink'.
        flat: If True, place all files in dest_dir without subdirectories.
        system: Optional system code for subdirectory naming.
        on_progress: Optional callback receiving ProgressEvent updates.

    Returns:
        Dict with 'transferred', 'skipped', and 'errors' counts.
    """
    if flat or not system:
        target_dir = dest_dir
    else:
        target_dir = dest_dir / system

    target_dir.mkdir(parents=True, exist_ok=True)

    stats: Dict[str, int] = {'transferred': 0, 'skipped': 0, 'errors': 0}

    for i, src in enumerate(files):
        if on_progress:
            on_progress(ProgressEvent(
                phase='transferring', current=i + 1, total=len(files),
                message=src.name, system=system or ''
            ))

        dst = target_dir / src.name
        if dst.exists():
            stats['skipped'] += 1
            continue

        try:
            if mode == 'copy':
                shutil.copy2(src, dst)
            elif mode == 'move':
                shutil.move(str(src), str(dst))
            elif mode == 'link':
                os.symlink(src, dst)
            elif mode == 'hardlink':
                os.link(src, dst)
            else:
                shutil.copy2(src, dst)
            stats['transferred'] += 1
        except OSError:
            stats['errors'] += 1

    return stats
