#!/usr/bin/env python3
"""Analyze title mappings across all supported systems.

Downloads No-Intro/Redump/T-En DATs for every supported system, parses
entries, builds title groups, and identifies ungrouped regional variants
(Japan-only vs West-only groups) that may need title mappings.

Usage:
    python tools/analyze_title_mappings.py [--fresh]
"""

import argparse
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

# Allow imports from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from retro_refiner.dat import (  # noqa: E402
    download_libretro_dat,
    download_ten_dat,
    fetch_ten_dat_listing,
    normalize_title,
    parse_dat_file,
)
from retro_refiner.filter import parse_rom_filename  # noqa: E402
from retro_refiner.systems import load_system_data  # noqa: E402

SKIP_SYSTEMS = frozenset({
    'mame', 'fbneo', 'fba', 'arcade',
    'cps1', 'cps2', 'cps3',
    'naomi', 'naomi2', 'atomiswave',
    'model2', 'model3',
    'neogeo',
    'daphne',
})


class EntryInfo(NamedTuple):
    """Parsed DAT entry with title grouping info."""
    name: str
    base_title: str
    normalized: str
    region: str
    size: int
    is_ten: bool


def download_all_dats(dat_dir: Path,
                       force: bool = False) -> Dict[str, List[Path]]:
    """Download all DATs for every supported system.

    Returns a dict mapping system name to list of DAT file paths.
    """
    sdata = load_system_data()
    systems = sorted(sdata.libretro_dat_systems.keys())
    result: Dict[str, List[Path]] = defaultdict(list)

    # --- No-Intro / Redump DATs (parallel) ---
    print(f"Downloading No-Intro/Redump DATs for {len(systems)} systems ...")
    completed = 0

    def _download_one(system: str) -> Tuple[str, Optional[Path]]:
        path = download_libretro_dat(system, dat_dir, force=force)
        return system, path

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_download_one, s): s for s in systems}
        for future in as_completed(futures):
            system, path = future.result()
            if path:
                result[system].append(path)
            completed += 1
            if completed % 20 == 0 or completed == len(systems):
                print(f"  {completed}/{len(systems)} systems done")

    # --- T-En DATs (sequential, needs listing first) ---
    print("Fetching T-En DAT listing ...")
    listing = fetch_ten_dat_listing()
    if listing:
        ten_systems = [s for s in systems if s not in SKIP_SYSTEMS]
        print(f"Downloading T-En DATs for {len(ten_systems)} systems ...")
        ten_count = 0
        for system in ten_systems:
            path = download_ten_dat(system, dat_dir, force=force,
                                    listing_cache=listing)
            if path:
                result[system].append(path)
                ten_count += 1
        print(f"  {ten_count} T-En DATs downloaded")
    else:
        print("  T-En listing unavailable — skipping")

    return dict(result)


def parse_system_entries(system: str,
                          dat_paths: List[Path]) -> List[EntryInfo]:
    """Parse DAT files and return filtered entry info tuples."""
    entries: List[EntryInfo] = []

    for dat_path in dat_paths:
        is_ten = '_t-en' in dat_path.name.lower()

        try:
            dat_entries = parse_dat_file(dat_path)
        except Exception:  # pylint: disable=broad-except
            print(f"  WARNING: Failed to parse {dat_path.name}",
                  file=sys.stderr)
            continue

        for _key, dat_entry in dat_entries.items():
            game_name = dat_entry.name
            # dat_entry.name may already have an extension (.sfc, .nes, etc.)
            # parse_rom_filename expects a filename with extension
            if not os.path.splitext(game_name)[1]:
                game_name += '.zip'
            rom_info = parse_rom_filename(game_name)

            # Skip unwanted categories
            if any([
                rom_info.is_beta,
                rom_info.is_demo,
                rom_info.is_proto,
                rom_info.is_bios,
                rom_info.is_compilation,
                rom_info.has_hacks,
                rom_info.is_pirate,
                rom_info.is_sample,
            ]):
                continue

            normalized = normalize_title(rom_info.base_title)
            entries.append(EntryInfo(
                name=dat_entry.name,
                base_title=rom_info.base_title,
                normalized=normalized,
                region=rom_info.region,
                size=dat_entry.size,
                is_ten=is_ten,
            ))

    return entries


_JAPAN_REGIONS = frozenset({'Japan', 'Asia'})
_WEST_REGIONS = frozenset({'USA', 'Europe', 'World', 'Australia'})


def build_title_groups(
    entries: List[EntryInfo],
) -> Tuple[Dict[str, List[EntryInfo]], List[str], List[str]]:
    """Group entries by normalized title and find ungrouped variants.

    Returns:
        (groups, ungrouped_japan, ungrouped_west)
        - groups: dict of normalized_title -> list of entries
        - ungrouped_japan: normalized titles that have Japan/Asia but
          no USA/Europe/World/Australia entries
        - ungrouped_west: normalized titles that have Western regions
          but no Japan/Asia entries
    """
    groups: Dict[str, List[EntryInfo]] = defaultdict(list)
    for entry in entries:
        groups[entry.normalized].append(entry)

    ungrouped_japan: List[str] = []
    ungrouped_west: List[str] = []

    for title, group_entries in groups.items():
        regions = {e.region for e in group_entries}

        has_japan = bool(regions & _JAPAN_REGIONS)
        has_west = bool(regions & _WEST_REGIONS)

        if has_japan and not has_west:
            ungrouped_japan.append(title)
        elif has_west and not has_japan:
            ungrouped_west.append(title)

    return dict(groups), sorted(ungrouped_japan), sorted(ungrouped_west)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze title mappings across all supported systems')
    parser.add_argument('--fresh', action='store_true',
                        help='Force re-download of all DAT files')
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    dat_dir = project_root / 'dat_files'

    # Download
    system_dats = download_all_dats(dat_dir, force=args.fresh)
    print(f"\nDATs available for {len(system_dats)} systems\n")

    # Analyze
    total_groups = 0
    total_japan = 0
    total_west = 0
    total_entries = 0
    systems_with_ungrouped = 0

    for system in sorted(system_dats.keys()):
        if system in SKIP_SYSTEMS:
            continue

        dat_paths = system_dats[system]
        entries = parse_system_entries(system, dat_paths)
        if not entries:
            continue

        groups, ungrouped_japan, ungrouped_west = build_title_groups(entries)

        total_entries += len(entries)
        total_groups += len(groups)
        total_japan += len(ungrouped_japan)
        total_west += len(ungrouped_west)

        if ungrouped_japan or ungrouped_west:
            systems_with_ungrouped += 1
            print(f"=== {system} ===")
            print(f"  Entries: {len(entries)}  "
                  f"Groups: {len(groups)}  "
                  f"Japan-only: {len(ungrouped_japan)}  "
                  f"West-only: {len(ungrouped_west)}")

            if ungrouped_japan:
                print(f"  Sample Japan-only ({min(5, len(ungrouped_japan))}):")
                for title in ungrouped_japan[:5]:
                    print(f"    - {title}")

            if ungrouped_west:
                print(f"  Sample West-only ({min(5, len(ungrouped_west))}):")
                for title in ungrouped_west[:5]:
                    print(f"    - {title}")
            print()

    # Summary
    print("=" * 60)
    print("TOTALS")
    print(f"  Systems analyzed: {len(system_dats) - len(SKIP_SYSTEMS)}")
    print(f"  Total entries: {total_entries}")
    print(f"  Total title groups: {total_groups}")
    print(f"  Japan-only groups: {total_japan}")
    print(f"  West-only groups: {total_west}")
    print(f"  Systems with ungrouped: {systems_with_ungrouped}")


if __name__ == '__main__':
    main()
