"""File transfer: copy/move/symlink/hardlink ROM files to destination.

Also includes playlist and gamelist generation helpers.
"""
import json
import os
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from retro_refiner.log import logger
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
    logger.debug("Transferring {} files to {} (mode={})", len(files), target_dir, mode)

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
                os.symlink(src.resolve(), dst)
            elif mode == 'hardlink':
                os.link(src, dst)
            else:
                shutil.copy2(src, dst)
            stats['transferred'] += 1
        except OSError as exc:
            logger.error("Transfer failed for {}: {}", src.name, exc)
            stats['errors'] += 1

    logger.debug("Transfer complete: {} transferred, {} skipped, {} errors",
                 stats['transferred'], stats['skipped'], stats['errors'])
    return stats


def validate_destination(dest_dir: Path, system: Optional[str],
                         flat: bool, expected_files: Dict[str, int],
                         crc_check: bool = False,
                         crc_data: Optional[Dict[str, str]] = None,
                         on_progress: Optional[Callable] = None  # pylint: disable=unused-argument
                         ) -> Dict[str, str]:
    """Validate files already in destination directory.

    Args:
        dest_dir: Destination directory.
        system: System code for subdirectory.
        flat: If True, files are directly in dest_dir.
        expected_files: Dict of filename -> expected_size.
        crc_check: If True, also verify CRC32 (requires crc_data).
        crc_data: Dict of filename -> expected_crc32 hex string.
        on_progress: Optional progress callback.

    Returns:
        Dict of filename -> status ('valid', 'invalid', 'missing').
    """
    target_dir = dest_dir if (flat or not system) else dest_dir / system
    logger.debug("Validating {} expected files in {}", len(expected_files), target_dir)
    result = {}
    for filename, expected_size in expected_files.items():
        filepath = target_dir / filename
        if not filepath.exists():
            result[filename] = 'missing'
            continue
        if expected_size == 0:
            # Unknown size — file exists, assume valid
            result[filename] = 'valid'
            continue
        actual_size = filepath.stat().st_size
        if actual_size != expected_size:
            result[filename] = 'invalid'
            continue
        if crc_check and crc_data and filename in crc_data:
            from retro_refiner.dat import calculate_crc32  # pylint: disable=import-outside-toplevel
            actual_crc = calculate_crc32(filepath)
            if actual_crc != crc_data[filename]:
                result[filename] = 'invalid'
                continue
        result[filename] = 'valid'
    valid = sum(1 for v in result.values() if v == 'valid')
    invalid = sum(1 for v in result.values() if v == 'invalid')
    missing = sum(1 for v in result.values() if v == 'missing')
    logger.debug("Validation: {} valid, {} invalid, {} missing", valid, invalid, missing)
    return result


def clean_destination(dest_dir: Path, system: Optional[str],
                      flat: bool, keep_files: set,
                      on_progress: Optional[Callable] = None  # pylint: disable=unused-argument
                      ) -> Dict[str, int]:
    """Remove files from destination that aren't in the keep set.

    Args:
        dest_dir: Destination directory.
        system: System code for subdirectory.
        flat: If True, files are directly in dest_dir.
        keep_files: Set of filenames to keep.
        on_progress: Optional progress callback.

    Returns:
        Dict with 'removed' and 'errors' counts.
    """
    target_dir = dest_dir if (flat or not system) else dest_dir / system
    stats = {'removed': 0, 'errors': 0}
    if not target_dir.exists():
        return stats
    for filepath in target_dir.iterdir():
        if filepath.is_file() and filepath.name not in keep_files:
            try:
                filepath.unlink()
                logger.debug("Cleaned: {}", filepath.name)
                stats['removed'] += 1
            except OSError as exc:
                logger.error("Failed to clean {}: {}", filepath.name, exc)
                stats['errors'] += 1
    if stats['removed']:
        logger.debug("Cleaned {} files from {}", stats['removed'], target_dir)
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
    logger.debug("Generated M3U playlist: {} ({} entries)", playlist_path, len(rom_files))
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
        lines.append('  <game>')
        lines.append(f'    <path>./{xml_escape(rom.name)}</path>')
        lines.append(f'    <name>{xml_escape(rom.stem)}</name>')
        lines.append('  </game>')
    lines.append('</gameList>')

    with open(gamelist_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    logger.debug("Generated gamelist.xml: {} ({} entries)", gamelist_path, len(rom_files))
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
    logger.debug("Generated RetroArch playlist: {} ({} entries)",
                 playlist_path, len(entries))
    return playlist_path
