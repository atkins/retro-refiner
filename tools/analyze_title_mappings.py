#!/usr/bin/env python3
"""Analyze DAT files to find missing title mappings across all systems.

Downloads No-Intro, Redump, and T-En DATs for every supported system,
then detects regional variants that fail to group under normalize_title().
High-confidence mappings are added directly to title_mappings.json.
Low-confidence candidates are written to tools/mapping_review.txt.

Usage:
    python tools/analyze_title_mappings.py          # use cached DATs
    python tools/analyze_title_mappings.py --fresh   # force re-download
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

# Allow imports from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# pylint: disable=import-error,wrong-import-position
from retro_refiner.dat import (  # noqa: E402
    download_libretro_dat,
    download_ten_dat,
    fetch_ten_dat_listing,
    load_title_mappings,
    normalize_title,
    parse_dat_file,
    reset_title_mappings_cache,
)
from retro_refiner.filter import parse_rom_filename  # noqa: E402
from retro_refiner.systems import load_system_data  # noqa: E402
# pylint: enable=import-error,wrong-import-position

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


def parse_system_entries(dat_paths: List[Path]) -> List[EntryInfo]:
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


# --- Mapping type returned by detection methods ---

class MappingCandidate(NamedTuple):
    """A candidate title mapping found by one of the detection methods."""
    variant: str       # normalized title (the one to remap)
    canonical: str     # normalized title (the target)
    variant_name: str  # original ROM name for context
    canonical_name: str
    method: str        # 'ten_crossref', 'size_match', or 'fuzzy'
    score: float       # confidence (1.0 for methods 1-2, 0-1 for fuzzy)


# --- Method 1: T-En cross-reference ---

def find_ten_mappings(entries: List[EntryInfo]) -> List[MappingCandidate]:
    """Find mappings by cross-referencing T-En entries with official DATs.

    For each T-En entry (fan translation), find the corresponding official
    entry by ROM size. If normalized titles differ, that's a missing mapping.
    """
    ten_entries = [e for e in entries if e.is_ten]
    official_entries = [e for e in entries if not e.is_ten]

    if not ten_entries or not official_entries:
        return []

    # Build lookups
    official_by_norm: Dict[str, List[EntryInfo]] = defaultdict(list)
    official_by_size: Dict[int, List[EntryInfo]] = defaultdict(list)
    for entry in official_entries:
        official_by_norm[entry.normalized].append(entry)
        official_by_size[entry.size].append(entry)

    mappings: List[MappingCandidate] = []
    for ten_entry in ten_entries:
        # Already groups with an official entry?
        if ten_entry.normalized in official_by_norm:
            continue

        # Try exact size match, then near-size (within 1KB)
        size_matches = official_by_size.get(ten_entry.size, [])
        if not size_matches:
            for delta in range(1, 1025):
                size_matches = (
                    official_by_size.get(ten_entry.size + delta, [])
                    + official_by_size.get(ten_entry.size - delta, [])
                )
                if size_matches:
                    break

        if not size_matches:
            continue

        # Pick best match — prefer USA, then World, then Europe
        best = _pick_best_western(size_matches)
        if best and best.normalized != ten_entry.normalized:
            mappings.append(MappingCandidate(
                variant=ten_entry.normalized,
                canonical=best.normalized,
                variant_name=ten_entry.name,
                canonical_name=best.name,
                method='ten_crossref',
                score=1.0,
            ))

    return mappings


def _pick_best_western(candidates: List[EntryInfo]) -> Optional[EntryInfo]:
    """Pick the best western-region entry from a list of candidates."""
    best = None
    for entry in candidates:
        if entry.region in ('USA', 'World', 'Europe', 'Australia'):
            if best is None or (entry.region == 'USA' and best.region != 'USA'):
                best = entry
    return best if best else (candidates[0] if candidates else None)


# --- Method 2: Size-matched regional variants ---

def find_size_matched_mappings(
    entries: List[EntryInfo],
) -> List[MappingCandidate]:
    """Find mappings by matching ROM sizes across regions.

    When a Japan entry has the exact same ROM size as a USA/Europe entry
    AND that size is unique to those two entries, they're very likely the
    same game. If normalized titles differ, that's a missing mapping.

    Only considers sizes shared by exactly 1 Japan and 1 Western entry
    (with revisions allowed) to avoid false positives from common sizes.
    """
    official = [e for e in entries if not e.is_ten]

    japan_entries = [e for e in official if e.region in _JAPAN_REGIONS]
    west_entries = [e for e in official if e.region in _WEST_REGIONS]

    if not japan_entries or not west_entries:
        return []

    # Group by size for each region
    jp_by_size: Dict[int, List[EntryInfo]] = defaultdict(list)
    for entry in japan_entries:
        jp_by_size[entry.size].append(entry)

    west_by_size: Dict[int, List[EntryInfo]] = defaultdict(list)
    for entry in west_entries:
        west_by_size[entry.size].append(entry)

    west_norms = {e.normalized for e in west_entries}

    mappings: List[MappingCandidate] = []
    seen: Set[Tuple[str, str]] = set()

    for size, jp_at_size in jp_by_size.items():
        west_at_size = west_by_size.get(size)
        if not west_at_size:
            continue

        # Get unique normalized titles at this size per region
        jp_titles = {e.normalized for e in jp_at_size}
        west_titles = {e.normalized for e in west_at_size}

        # Only consider if there's exactly 1 unique JP title and
        # 1 unique Western title at this size (allows revisions)
        if len(jp_titles) != 1 or len(west_titles) != 1:
            continue

        jp_norm = next(iter(jp_titles))
        west_norm = next(iter(west_titles))

        # Already match via normalization?
        if jp_norm == west_norm or jp_norm in west_norms:
            continue

        key = (jp_norm, west_norm)
        if key in seen:
            continue
        seen.add(key)

        jp_entry = jp_at_size[0]
        best = _pick_best_western(west_at_size)
        if best:
            mappings.append(MappingCandidate(
                variant=jp_norm,
                canonical=best.normalized,
                variant_name=jp_entry.name,
                canonical_name=best.name,
                method='size_match',
                score=1.0,
            ))

    return mappings


# --- Method 3: Fuzzy title matching ---

def find_fuzzy_mappings(
    entries: List[EntryInfo],
    already_found: Set[str],
) -> List[MappingCandidate]:
    """Find potential mappings via fuzzy string matching.

    These are LOW confidence — written to review file only, not auto-added.

    Args:
        entries: All parsed entries for a system.
        already_found: Set of variant normalized titles already found by
            methods 1-2, to avoid duplicates.
    """
    official = [e for e in entries if not e.is_ten]

    japan_entries = [e for e in official if e.region in _JAPAN_REGIONS]
    west_entries = [e for e in official if e.region in _WEST_REGIONS]

    if not japan_entries or not west_entries:
        return []

    west_norms = {e.normalized for e in west_entries}
    unmapped_jp = [
        e for e in japan_entries
        if e.normalized not in already_found
        and e.normalized not in west_norms
    ]

    # Build unique western normalized titles
    west_unique: Dict[str, EntryInfo] = {}
    for entry in west_entries:
        if entry.normalized not in west_unique:
            west_unique[entry.normalized] = entry

    candidates: List[MappingCandidate] = []
    for jp_entry in unmapped_jp:
        best_score = 0.0
        best_match = None

        for west_norm, west_entry in west_unique.items():
            score = SequenceMatcher(
                None, jp_entry.normalized, west_norm).ratio()
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = west_entry

        if best_match and best_score >= 0.6:
            candidates.append(MappingCandidate(
                variant=jp_entry.normalized,
                canonical=best_match.normalized,
                variant_name=jp_entry.name,
                canonical_name=best_match.name,
                method='fuzzy',
                score=best_score,
            ))

    return candidates


# --- Validation of existing mappings ---

def validate_existing_mappings(
    all_normalized: Set[str],
) -> Tuple[List[Tuple[str, str, str]],
           List[Tuple[str, str, str]],
           List[Tuple[str, str, str]]]:
    """Validate existing title mappings against DAT data.

    Returns:
        orphaned: (variant, canonical, category) — variant not in any DAT
        redundant: (variant, canonical, category) — variant == canonical
        bad_canonical: (variant, canonical, category) — canonical not in DATs
    """
    mappings_path = (Path(__file__).resolve().parent.parent
                     / 'data' / 'title_mappings.json')
    with open(mappings_path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)

    orphaned: List[Tuple[str, str, str]] = []
    redundant: List[Tuple[str, str, str]] = []
    bad_canonical: List[Tuple[str, str, str]] = []

    for category, cat_entries in data.items():
        if category.startswith('_') or not isinstance(cat_entries, dict):
            continue
        for variant, canonical in cat_entries.items():
            if variant == canonical:
                redundant.append((variant, canonical, category))
            elif variant not in all_normalized:
                orphaned.append((variant, canonical, category))
            elif canonical not in all_normalized:
                bad_canonical.append((variant, canonical, category))

    return orphaned, redundant, bad_canonical


# --- Apply mappings to title_mappings.json ---

def apply_mappings(
    new_mappings: List[Tuple[str, MappingCandidate]],
    orphaned: List[Tuple[str, str, str]],
    redundant: List[Tuple[str, str, str]],
) -> Tuple[int, int]:
    """Apply high-confidence mappings to title_mappings.json.

    Args:
        new_mappings: list of (system, MappingCandidate) tuples.
        orphaned: mappings to remove (variant not in DATs).
        redundant: mappings to remove (variant == canonical).

    Returns (added_count, removed_count).
    """
    mappings_path = (Path(__file__).resolve().parent.parent
                     / 'data' / 'title_mappings.json')
    with open(mappings_path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)

    # Load existing flat mappings to avoid duplicates
    existing_flat: Dict[str, str] = {}
    for cat, cat_entries in data.items():
        if cat.startswith('_') or not isinstance(cat_entries, dict):
            continue
        existing_flat.update(cat_entries)

    # Remove orphaned and redundant
    removed = 0
    remove_set = {(v, c) for v, c, _ in orphaned + redundant}
    for category in list(data.keys()):
        if category.startswith('_') or not isinstance(data[category], dict):
            continue
        to_remove = [v for v, c in data[category].items()
                     if (v, c) in remove_set]
        for v in to_remove:
            del data[category][v]
            removed += 1
        if not data[category]:
            del data[category]

    # Add new mappings
    added = 0
    for system, candidate in new_mappings:
        if candidate.variant in existing_flat:
            continue
        if candidate.variant == candidate.canonical:
            continue

        cat_name = (f'translations_{system}'
                    if candidate.method == 'ten_crossref'
                    else f'regional_{system}')

        if cat_name not in data:
            data[cat_name] = {}

        data[cat_name][candidate.variant] = candidate.canonical
        existing_flat[candidate.variant] = candidate.canonical
        added += 1

    # Update metadata
    if '_meta' in data:
        data['_meta']['updated'] = str(date.today())

    # Write back sorted
    sorted_data: dict = {}
    if '_meta' in data:
        sorted_data['_meta'] = data['_meta']
    for key in sorted(k for k in data if k != '_meta'):
        sorted_data[key] = dict(sorted(data[key].items()))

    with open(mappings_path, 'w', encoding='utf-8') as fh:
        json.dump(sorted_data, fh, indent=2, ensure_ascii=False)
        fh.write('\n')

    return added, removed


# --- Write review file for fuzzy candidates ---

def write_review_file(
    candidates: List[Tuple[str, MappingCandidate]],
) -> None:
    """Write review candidates (size-match + fuzzy) to file."""
    review_path = Path(__file__).resolve().parent / 'mapping_review.txt'

    # Sort by method (size_match first) then by system
    sorted_candidates = sorted(candidates,
                               key=lambda x: (x[1].method, x[0]))

    with open(review_path, 'w', encoding='utf-8') as fh:
        fh.write("# Title Mapping Review Candidates\n")
        fh.write(f"# Generated: {date.today()}\n")
        fh.write("# size_match = same ROM size, different titles\n")
        fh.write("# fuzzy = similar title strings\n")
        fh.write("# Review and add good ones to "
                 "data/title_mappings.json manually.\n\n")

        for system, candidate in sorted_candidates:
            score_str = (f" score={candidate.score:.2f}"
                         if candidate.method == 'fuzzy' else '')
            fh.write(f"[{system}] {candidate.method}{score_str}\n")
            fh.write(f"  JP: {candidate.variant_name}\n")
            fh.write(f"      normalized: {candidate.variant}\n")
            fh.write(f"  EN: {candidate.canonical_name}\n")
            fh.write(f"      normalized: {candidate.canonical}\n\n")

    print(f"Review file written: {review_path}")
    print(f"  {len(candidates)} candidates to review")


# --- Generate regression tests ---

def generate_tests(
    new_mappings: List[Tuple[str, MappingCandidate]],
) -> int:
    """Append regression tests to test_selection.py for new mappings.

    Returns count of tests added.
    """
    if not new_mappings:
        return 0

    test_path = (Path(__file__).resolve().parent.parent
                 / 'tests' / 'test_selection.py')
    content = test_path.read_text(encoding='utf-8')

    # Check if generated test function already exists
    if 'def test_generated_title_mappings' in content:
        return 0  # don't duplicate

    # Build test function
    lines = [
        "",
        "",
        "def test_generated_title_mappings():",
        '    """Auto-generated tests for title mappings '
        'from analyze_title_mappings.py."""',
        "    from retro_refiner.dat import normalize_title",
        "",
    ]

    count = 0
    seen: Set[Tuple[str, str]] = set()
    for system, candidate in new_mappings:
        key = (candidate.variant, candidate.canonical)
        if key in seen:
            continue
        seen.add(key)
        var_esc = candidate.variant_name.replace("'", "\\'")
        can_esc = candidate.canonical_name.replace("'", "\\'")
        lines.append(f"    # {system}: {candidate.method}")
        lines.append("    result.assert_equal(")
        lines.append(
            f"        normalize_title(parse_rom_filename("
            f"'{var_esc}.zip').base_title),")
        lines.append(
            f"        normalize_title(parse_rom_filename("
            f"'{can_esc}.zip').base_title),")
        lines.append(f"        '{var_esc} should map to {can_esc}')")
        lines.append("")
        count += 1

    if count == 0:
        return 0

    # Find insertion point — before "if __name__ == '__main__':"
    marker = "if __name__ == '__main__':"
    idx = content.rfind(marker)
    if idx == -1:
        print("WARNING: Could not find insertion point in test file")
        return 0

    test_func = '\n'.join(lines) + '\n\n\n'
    new_content = content[:idx] + test_func + content[idx:]

    # Find and insert test call in main()
    # Look for last test call before the closing of main
    call_marker = "    test_backward_compat_config()"
    call_idx = new_content.rfind(call_marker)
    if call_idx != -1:
        insert_pos = call_idx + len(call_marker)
        call_line = "\n    test_generated_title_mappings()"
        new_content = (new_content[:insert_pos]
                       + call_line
                       + new_content[insert_pos:])

    test_path.write_text(new_content, encoding='utf-8')
    return count


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze DAT files for missing title mappings')
    parser.add_argument('--fresh', action='store_true',
                        help='Force re-download of all DAT files')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report findings without modifying files')
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    dat_dir = project_root / 'dat_files'

    # 1. Download DATs
    system_dats = download_all_dats(dat_dir, force=args.fresh)
    print(f"\nDATs available for {len(system_dats)} systems\n")

    # 2. Parse all systems (cache results)
    system_entries: Dict[str, List[EntryInfo]] = {}
    all_normalized: Set[str] = set()

    for system in sorted(system_dats.keys()):
        if system in SKIP_SYSTEMS:
            continue
        entries = parse_system_entries(system_dats[system])
        if entries:
            system_entries[system] = entries
            all_normalized.update(e.normalized for e in entries)

    print(f"Parsed {sum(len(e) for e in system_entries.values())} entries "
          f"across {len(system_entries)} systems\n")

    # 3-5. Run detection methods per system
    all_mappings: List[Tuple[str, MappingCandidate]] = []  # auto-add
    all_review: List[Tuple[str, MappingCandidate]] = []    # review only

    for system, entries in sorted(system_entries.items()):
        # Method 1: T-En cross-reference (auto-add)
        ten_maps = find_ten_mappings(entries)
        for mapping in ten_maps:
            all_mappings.append((system, mapping))

        # Method 2: Size-matched regional variants (review only —
        # size alone produces too many false positives)
        size_maps = find_size_matched_mappings(entries)
        for mapping in size_maps:
            all_review.append((system, mapping))

        # Method 3: Fuzzy matching (review only)
        already_found = {m.variant for s, m in all_mappings if s == system}
        already_found |= {m.variant for s, m in all_review if s == system}
        fuzzy = find_fuzzy_mappings(entries, already_found)
        for mapping in fuzzy:
            all_review.append((system, mapping))

    # Deduplicate auto-add mappings
    seen_variants: Set[str] = set()
    deduped: List[Tuple[str, MappingCandidate]] = []
    for system, mapping in all_mappings:
        if mapping.variant not in seen_variants:
            seen_variants.add(mapping.variant)
            deduped.append((system, mapping))
    all_mappings = deduped

    ten_count = sum(1 for _, m in all_mappings if m.method == 'ten_crossref')
    size_count = sum(1 for _, m in all_review if m.method == 'size_match')
    fuzzy_count = sum(1 for _, m in all_review if m.method == 'fuzzy')
    print(f"Method 1 (T-En cross-ref): {ten_count} auto-add")
    print(f"Method 2 (size match):     {size_count} for review")
    print(f"Method 3 (fuzzy):          {fuzzy_count} for review\n")

    # 6. Validate existing mappings
    orphaned, redundant, bad_canonical = validate_existing_mappings(
        all_normalized)
    print("Validation of existing mappings:")
    print(f"  Not in DATs (informational):       {len(orphaned)}")
    print(f"  Redundant (variant == canonical):   {len(redundant)} (will remove)")
    print(f"  Bad canonical (target not in DATs): {len(bad_canonical)}")

    if bad_canonical:
        print("  Bad canonical entries:")
        for variant, canonical, category in bad_canonical[:10]:
            print(f"    [{category}] {variant} -> {canonical}")
    print()

    if args.dry_run:
        print("DRY RUN — no files modified")
        return

    # 7. Apply high-confidence mappings to title_mappings.json
    # Only remove redundant (v==c) entries — orphaned entries may serve
    # legitimate purposes for non-DAT ROM naming conventions.
    added, removed = apply_mappings(all_mappings, [], redundant)

    # 8. Write review file (size-match + fuzzy candidates)
    write_review_file(all_review)

    # 9. Generate regression tests
    reset_title_mappings_cache()
    current_mappings = load_title_mappings()
    actually_added = [
        (s, m) for s, m in all_mappings
        if m.variant in current_mappings
        and current_mappings[m.variant] == m.canonical
    ]
    test_count = generate_tests(actually_added)

    # 10. Summary
    print(f"\nResults:")
    print(f"  Mappings added:    {added}")
    print(f"  Mappings removed:  {removed}")
    print(f"  Tests generated:   {test_count}")
    print(f"  Candidates for review: {len(all_review)}")


if __name__ == '__main__':
    main()
