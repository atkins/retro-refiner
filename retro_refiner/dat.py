"""DAT file operations: loading, parsing, CRC verification."""
from pathlib import Path
from typing import Callable, Dict, Optional


def load_dat_entries(system: str, dat_dir: Path) -> Dict[str, object]:
    """Load DAT entries for a system.

    Returns dict of ROM name -> DatRomEntry from the monolith.

    Args:
        system: System code (e.g. 'snes', 'genesis').
        dat_dir: Directory containing DAT files.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().load_all_system_dats(system, dat_dir)


def download_dat(system: str, dat_dir: Path,
                 on_progress: Callable = None) -> Optional[Path]:
    """Download DAT file for a system.

    Returns the path to the downloaded file, or None on failure.

    Args:
        system: System code.
        dat_dir: Directory to store downloaded DATs.
        on_progress: Optional progress callback.
    """
    _ = on_progress  # Reserved for future progress reporting
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().download_libretro_dat(system, dat_dir)


def parse_rom_filename(filename: str) -> object:
    """Parse a ROM filename into a RomInfo object.

    The returned object has fields like title, region, languages,
    revision, is_beta, is_proto, etc.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().parse_rom_filename(filename)


def normalize_title(title: str) -> str:
    """Normalize a ROM title for grouping.

    Lowercases, strips punctuation, converts Roman numerals to Arabic,
    and applies title mappings from data/title_mappings.json.
    """
    from retro_refiner._monolith import get_module  # pylint: disable=import-outside-toplevel
    return get_module().normalize_title(title)
