"""Cross-platform deduplication: analysis and PC game list parsing.

Standalone implementations extracted from the monolith. Console output is
replaced by plain stdout/stderr for portability.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from retro_refiner.dat import normalize_title, normalize_title_for_dedupe
from retro_refiner.network import format_size


def parse_pc_game_list(xml_path, for_dedupe=False):
    """Parse LaunchBox playlist XML to extract normalized game titles.

    Args:
        xml_path: Path to the LaunchBox playlist XML file.
        for_dedupe: If True, use dedupe-safe normalization (preserves articles).

    Returns:
        Set of normalized title strings.
    """
    normalizer = normalize_title_for_dedupe if for_dedupe else normalize_title
    titles = set()
    path = Path(xml_path)
    if not path.exists():
        print(f"WARNING: PC game list not found: {xml_path}", file=sys.stderr)
        return titles
    try:
        for _, elem in ET.iterparse(str(path), events=('end',)):
            if elem.tag == 'GameTitle' and elem.text:
                normalized = normalizer(elem.text.strip())
                if normalized:
                    titles.add(normalized)
            elem.clear()
    except ET.ParseError as exc:
        print(f"WARNING: Failed to parse PC game list {xml_path}: {exc}",
              file=sys.stderr)
    return titles


def run_dedupe_analysis(detected, args, delete=False, confirm=True):
    """Run cross-platform dedupe analysis and optionally delete duplicates.

    Args:
        detected: Dict of {system_code: [Path, ...]} with discovered ROM files.
        args: Namespace with dedupe_priority, dedupe_pc_lists, verbose attributes.
        delete: If True, delete duplicate files after analysis.
        confirm: If True, prompt before deleting (ignored when delete=False).
    """
    # Import parse_rom_filename here to avoid circular imports
    from retro_refiner.filter import parse_rom_filename  # pylint: disable=import-outside-toplevel

    arcade_systems = {'mame', 'fbneo', 'fba', 'arcade', 'teknoparrot'}

    dedupe_priority_list = [s.strip().lower()
                            for s in args.dedupe_priority.split(',')]
    priority_systems = [s for s in dedupe_priority_list
                        if s != 'pc' and s not in arcade_systems
                        and s in detected]

    if not priority_systems:
        print("WARNING: No priority systems found in detected ROMs",
              file=sys.stderr)
        return

    # Load PC game lists as seed
    pc_title_sources = {}
    if args.dedupe_pc_lists:
        for xml_path in args.dedupe_pc_lists:
            source_name = Path(xml_path).stem
            titles = parse_pc_game_list(Path(xml_path), for_dedupe=True)
            for title in titles:
                if title not in pc_title_sources:
                    pc_title_sources[title] = source_name
    pc_title_count = len(pc_title_sources)
    claimed_titles = set(pc_title_sources)

    # Build title sets, size maps, and file maps
    system_titles = {}
    system_title_files = {}
    for system in priority_systems:
        title_sizes = {}
        title_files = {} if delete else None
        for f in detected[system]:
            rom = parse_rom_filename(f.name)
            normalized = normalize_title_for_dedupe(rom.base_title)
            if normalized:
                size = f.stat().st_size if f.exists() else 0
                if normalized in title_sizes:
                    title_sizes[normalized] += size
                else:
                    title_sizes[normalized] = size
                if delete:
                    title_files.setdefault(normalized, []).append(f)
        if title_sizes:
            system_titles[system] = title_sizes
            if delete:
                system_title_files[system] = title_files

    # Display results
    header = ("CROSS-PLATFORM DEDUPE DELETE" if delete
              else "CROSS-PLATFORM DEDUPE ANALYSIS")
    print(f"\n  {header}")

    priority_display = [s.upper() for s in dedupe_priority_list]
    if pc_title_count > 0:
        priority_display = ['PC'] + [s for s in priority_display if s != 'PC']
    print(f"  Priority chain: {' > '.join(priority_display)}")

    if pc_title_count > 0:
        print(f"  PC: {pc_title_count:,} titles (from game lists)")

    # Table header
    widths = [12, 8, 12, 12, 13, 6]
    hdr = ['System', 'Titles', 'Size', 'Duplicates', 'Reclaimable', '%']
    print()
    print('  ' + ''.join(h.ljust(w) for h, w in zip(hdr, widths)))
    print('  ' + '-' * 67)

    total_dupes = 0
    total_size = 0
    total_reclaimable = 0
    files_to_delete = {}

    active_systems = [s for s in priority_systems if s in system_titles]

    for system in active_systems:
        titles_map = system_titles[system]
        title_count = len(titles_map)
        system_size = sum(titles_map.values())
        duplicates = set()
        reclaimable = 0

        for title, size in titles_map.items():
            if title in claimed_titles:
                duplicates.add(title)
                reclaimable += size

        if delete and duplicates:
            delete_list = []
            for title in duplicates:
                delete_list.extend(
                    system_title_files.get(system, {}).get(title, []))
            files_to_delete[system] = delete_list

        dupe_count = len(duplicates)
        total_dupes += dupe_count
        total_size += system_size
        total_reclaimable += reclaimable

        pct = (dupe_count / title_count * 100) if title_count > 0 else 0.0
        row = [
            system.upper(),
            f"{title_count:,}",
            format_size(system_size),
            str(dupe_count),
            format_size(reclaimable),
            f"{pct:.1f}%"
        ]
        print('  ' + ''.join(str(v).ljust(w) for v, w in zip(row, widths)))

        for title in titles_map:
            claimed_titles.add(title)

    print('  ' + '-' * 67)
    total_row = [
        'TOTAL', '', format_size(total_size), str(total_dupes),
        format_size(total_reclaimable), ''
    ]
    print('  ' + ''.join(str(v).ljust(w)
                         for v, w in zip(total_row, widths)))

    # Delete duplicate files
    if delete and files_to_delete:
        total_file_count = sum(len(fl) for fl in files_to_delete.values())
        if confirm:
            print(f"\n  WARNING: This will permanently delete "
                  f"{total_file_count} duplicate files "
                  f"({format_size(total_reclaimable)}) from source "
                  f"directories.")
            try:
                response = input("  Continue? [y/N] ")
            except (EOFError, KeyboardInterrupt):
                response = ''
            if response.lower() not in ('y', 'yes'):
                print("  Cancelled")
                return
        total_deleted = 0
        total_freed = 0
        for system in active_systems:
            if system not in files_to_delete:
                continue
            deleted = 0
            freed = 0
            for f in files_to_delete[system]:
                if f.exists():
                    freed += f.stat().st_size
                    f.unlink()
                    deleted += 1
            total_deleted += deleted
            total_freed += freed
            print(f"  {system.upper()}: Deleted {deleted} duplicate files "
                  f"({format_size(freed)})")
        print(f"\n  Deleted {total_deleted} files, "
              f"freed {format_size(total_freed)}")
    elif delete:
        print("\n  No duplicate files to delete")
