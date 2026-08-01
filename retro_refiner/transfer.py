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
                   on_progress: Optional[Callable] = None,
                   relpaths: Optional[Dict[str, str]] = None
                   ) -> Dict[str, int]:
    """Transfer ROM files to destination directory.

    Args:
        files: List of source file paths to transfer.
        dest_dir: Destination directory.
        mode: Transfer mode - 'copy', 'move', 'link' (symlink), or 'hardlink'.
        flat: If True, place all files in dest_dir without subdirectories.
        system: Optional system code for subdirectory naming.
        on_progress: Optional callback receiving ProgressEvent updates.
        relpaths: Optional map of str(source path) -> destination-relative
            path, preserving subdirectory structure from recursive scans.
            Sources missing from the map fall back to their basename.

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

        rel = relpaths.get(str(src)) if relpaths else None
        dst = target_dir / (rel or src.name)
        if dst.exists():
            stats['skipped'] += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)

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


# Outputs this app generates into the destination itself. They are never
# in the keep set (which lists ROMs), so cleaning must skip them rather
# than delete and force a regenerate on every run.
_GENERATED_SUFFIXES = frozenset(('.m3u', '.xml', '.lpl', '.rrdownload'))


def clean_destination(dest_dir: Path, system: Optional[str],
                      flat: bool, keep_files: set,
                      on_progress: Optional[Callable] = None  # pylint: disable=unused-argument
                      ) -> Dict[str, int]:
    """Remove files from destination that aren't in the keep set.

    Args:
        dest_dir: Destination directory.
        system: System code for subdirectory.
        flat: If True, files are directly in dest_dir.
        keep_files: Set of destination-relative paths to keep, as written
            by the commit (POSIX separators). Bare filenames are also
            honoured so a flat destination keeps working.
        on_progress: Optional progress callback.

    Returns:
        Dict with 'removed' and 'errors' counts.
    """
    target_dir = dest_dir if (flat or not system) else dest_dir / system
    stats = {'removed': 0, 'errors': 0}
    if not target_dir.exists():
        return stats
    # Walk recursively: a recursive scan writes ROMs into subdirectories,
    # so a top-level-only pass would never see them.
    for filepath in target_dir.rglob('*'):
        if not filepath.is_file():
            continue
        if filepath.suffix.lower() in _GENERATED_SUFFIXES:
            continue
        rel = filepath.relative_to(target_dir).as_posix()
        if rel in keep_files or filepath.name in keep_files:
            continue
        try:
            filepath.unlink()
            logger.debug("Cleaned: {}", rel)
            stats['removed'] += 1
        except OSError as exc:
            logger.error("Failed to clean {}: {}", rel, exc)
            stats['errors'] += 1
    # Prune directories the cleaning emptied, deepest first.
    for dirpath in sorted(target_dir.rglob('*'), reverse=True):
        if dirpath.is_dir():
            try:
                dirpath.rmdir()
            except OSError:
                pass
    if stats['removed']:
        logger.debug("Cleaned {} files from {}", stats['removed'], target_dir)
    return stats


# =============================================================================
# Playlist and gamelist generation
# =============================================================================

def _rom_entry_path(rom: Path, base: Optional[Path]) -> str:
    """ROM path relative to ``base``, POSIX-style.

    A recursive scan puts ROMs in subdirectories, so a bare basename is
    both ambiguous (two subdirectories can hold the same name) and wrong
    for the emulator to resolve. Falls back to the basename when the ROM
    is not under ``base``.
    """
    if base is not None:
        try:
            return rom.relative_to(base).as_posix()
        except ValueError:
            pass
    return rom.name


def generate_m3u_playlist(system: str, rom_files: List[Path],
                          dest_path: Path) -> Path:
    """Generate M3U playlist for a system.

    Args:
        system: System code (used for filename).
        rom_files: List of ROM file paths.
        dest_path: Directory where the playlist is written. ROMs under it
            are listed by their path relative to it.

    Returns:
        Path to the generated .m3u file.
    """
    playlist_path = dest_path / f"{system}.m3u"
    with open(playlist_path, 'w', encoding='utf-8') as f:
        for rom in sorted(rom_files, key=lambda x: x.name.lower()):
            f.write(f"{_rom_entry_path(rom, dest_path)}\n")
    logger.debug("Generated M3U playlist: {} ({} entries)", playlist_path, len(rom_files))
    return playlist_path


def generate_gamelist_xml(_system: str, rom_files: List[Path],
                          dest_path: Path,
                          rom_dir: Optional[Path] = None) -> Path:
    """Generate EmulationStation gamelist.xml.

    Args:
        _system: System code (unused, kept for API symmetry).
        rom_files: List of ROM file paths.
        dest_path: Directory where gamelist.xml is written.
        rom_dir: Directory the ROMs live in. Given, entries are written as
            paths relative to it so ROMs in subdirectories resolve; without
            it they fall back to bare filenames.

    Returns:
        Path to the generated gamelist.xml file.
    """
    gamelist_path = dest_path / "gamelist.xml"

    lines = ['<?xml version="1.0"?>', '<gameList>']
    for rom in sorted(rom_files, key=lambda x: x.name.lower()):
        lines.append('  <game>')
        lines.append(
            f'    <path>./{xml_escape(_rom_entry_path(rom, rom_dir))}</path>')
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
            # rom is already absolute; joining rom_dir with the basename
            # would flatten away any subdirectory it lives in.
            "path": str(rom if rom.is_absolute() else rom_dir / rom.name),
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
