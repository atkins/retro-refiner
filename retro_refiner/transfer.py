"""File transfer: copy/move/symlink/hardlink ROM files to destination.

Also includes playlist and gamelist generation helpers.
"""
import json
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


# =============================================================================
# Playlist and gamelist generation
# =============================================================================

def generate_m3u_playlist(system: str, rom_files: List[Path],
                          dest_path: Path) -> Path:
    """Generate M3U playlist for a system.

    Args:
        system: System code (used for filename).
        rom_files: List of ROM file paths.
        dest_path: Directory where the playlist is written.

    Returns:
        Path to the generated .m3u file.
    """
    playlist_path = dest_path / f"{system}.m3u"
    with open(playlist_path, 'w', encoding='utf-8') as f:
        for rom in sorted(rom_files, key=lambda x: x.name.lower()):
            f.write(f"{rom.name}\n")
    return playlist_path


def generate_gamelist_xml(_system: str, rom_files: List[Path],
                          dest_path: Path) -> Path:
    """Generate EmulationStation gamelist.xml.

    Args:
        _system: System code (unused, kept for API symmetry).
        rom_files: List of ROM file paths.
        dest_path: Directory where gamelist.xml is written.

    Returns:
        Path to the generated gamelist.xml file.
    """
    gamelist_path = dest_path / "gamelist.xml"

    lines = ['<?xml version="1.0"?>', '<gameList>']
    for rom in sorted(rom_files, key=lambda x: x.name.lower()):
        name = rom.stem
        name_escaped = (name.replace('&', '&amp;')
                        .replace('<', '&lt;')
                        .replace('>', '&gt;')
                        .replace('"', '&quot;'))
        lines.append('  <game>')
        lines.append(f'    <path>./{rom.name}</path>')
        lines.append(f'    <name>{name_escaped}</name>')
        lines.append('  </game>')
    lines.append('</gameList>')

    with open(gamelist_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return gamelist_path


def generate_retroarch_playlist(system: str, rom_files: List[Path],
                                rom_dir: Path, playlist_dir: Path,
                                core_path: str = "DETECT") -> Path:
    """Generate Retroarch .lpl playlist.

    Args:
        system: System code.
        rom_files: List of ROM file paths.
        rom_dir: Directory containing the ROMs (used for playlist paths).
        playlist_dir: Directory where the .lpl is written.
        core_path: Core path for Retroarch entries.

    Returns:
        Path to the generated .lpl file.
    """
    playlist_path = playlist_dir / f"{system}.lpl"

    entries = []
    for rom in sorted(rom_files, key=lambda x: x.name.lower()):
        display_name = rom.stem
        entries.append({
            "path": str(rom_dir / rom.name),
            "label": display_name,
            "core_path": core_path,
            "core_name": "DETECT",
            "crc32": "",
            "db_name": f"{system}.lpl"
        })

    playlist = {
        "version": "1.5",
        "default_core_path": core_path,
        "default_core_name": "DETECT",
        "label_display_mode": 0,
        "right_thumbnail_mode": 0,
        "left_thumbnail_mode": 0,
        "sort_mode": 0,
        "items": entries
    }

    playlist_dir.mkdir(parents=True, exist_ok=True)
    with open(playlist_path, 'w', encoding='utf-8') as f:
        json.dump(playlist, f, indent=2)
    return playlist_path
