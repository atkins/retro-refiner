#!/usr/bin/env python3
"""
ROM Audit Tool — Analyze refined ROM collections for duplicates,
leaked filters, and missing games.

Uses retro-refiner's actual normalize_title() and parse_rom_filename()
for accurate results that match the real filtering pipeline.

Usage:
    python tools/audit.py refined/gba/                         # Audit one system
    python tools/audit.py refined/                             # Audit all systems
    python tools/audit.py refined/gba/ --dat dat_files/gba.dat # With missing-game check
"""

import re
import sys
import argparse
import importlib.util
from pathlib import Path
from collections import defaultdict

# Import retro-refiner module (hyphenated name requires importlib)
_spec = importlib.util.spec_from_file_location(
    "retro_refiner", Path(__file__).parent.parent / "retro-refiner.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

normalize_title = _module.normalize_title
parse_rom_filename = _module.parse_rom_filename
parse_dat_file = _module.parse_dat_file


# ---------------------------------------------------------------------------
# Selection log parser
# ---------------------------------------------------------------------------

def parse_selection_log(log_path):
    """Parse a _selection_log.txt and return a list of selected ROM entries.

    Each entry is a dict with keys:
        filename, title, region, revision, is_translation, is_proto
    """
    text = log_path.read_text(encoding='utf-8')

    # Find the SELECTED ROMS section
    sel_marker = 'SELECTED ROMS:\n'
    sel_start = text.find(sel_marker)
    if sel_start == -1:
        return []
    sel_start += len(sel_marker)

    # Skip the dashes line
    dash_end = text.find('\n', sel_start)
    if dash_end == -1:
        return []
    sel_start = dash_end + 1

    # Find the end of the selected section (SKIPPED GAMES or EOF)
    skip_marker = 'SKIPPED GAMES'
    sel_end = text.find(skip_marker, sel_start)
    if sel_end == -1:
        sel_end = len(text)

    section = text[sel_start:sel_end].strip()
    if not section:
        return []

    entries = []
    # Split into blocks separated by blank lines
    blocks = re.split(r'\n\n+', section)

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue

        # Line 0: filename (possibly with rating suffix like [★3.50 (42 votes)])
        filename = re.sub(r'\s*\[★[^\]]*\]$', '', lines[0].strip())

        # Line 1: "  Title: ..."
        title_match = re.match(r'\s*Title:\s*(.*)', lines[1])
        title = title_match.group(1).strip() if title_match else ''

        # Line 2: "  Region: ..., Rev: ...[, Translation: Yes][, Prototype: Yes]"
        meta_line = lines[2].strip()
        region_match = re.search(r'Region:\s*([^,]+)', meta_line)
        rev_match = re.search(r'Rev:\s*(\d+)', meta_line)
        is_translation = 'Translation: Yes' in meta_line
        is_proto = 'Prototype: Yes' in meta_line

        entries.append({
            'filename': filename,
            'title': title,
            'region': region_match.group(1).strip() if region_match else '',
            'revision': int(rev_match.group(1)) if rev_match else 0,
            'is_translation': is_translation,
            'is_proto': is_proto,
        })

    return entries


# ---------------------------------------------------------------------------
# Audit checks
# ---------------------------------------------------------------------------

def check_exact_duplicates(entries):
    """Find ROMs whose base titles normalize to the same string.

    Returns list of (normalized_title, [entry, ...]) tuples.
    """
    groups = defaultdict(list)
    for entry in entries:
        norm = normalize_title(entry['title'])
        groups[norm].append(entry)

    return [(norm, group) for norm, group in sorted(groups.items()) if len(group) >= 2]


def check_ten_japan_duplicates(entries):
    """Find [T-En] translations that coexist with a raw (Japan) ROM.

    Uses fuzzy word-overlap matching since titles may be completely different.
    Returns list of (translation_entry, japan_entry, common_words) tuples.
    """
    translations = []
    japan_roms = []

    for entry in entries:
        if '[T-En' in entry['filename']:
            translations.append(entry)
        elif entry['region'] == 'Japan' and not entry['is_translation']:
            japan_roms.append(entry)

    # Common Japanese/English words that don't indicate the same game
    stop_words = {
        'no', 'de', 'ga', 'wo', 'ni', 'wa', 'to', 'na', 'e',
        'the', 'of', 'and', 'a', 'in', 'for', 'on', 'at', 'is', 'it',
        'game', 'games', 'advance', 'vol', 'volume', 'vs',
    }

    # Pre-compute normalized titles and word sets
    ten_data = []
    for t in translations:
        norm = normalize_title(entry_base_title(t))
        words = set(norm.split()) - stop_words
        ten_data.append((t, norm, words))

    jp_data = []
    for j in japan_roms:
        norm = normalize_title(j['title'])
        words = set(norm.split()) - stop_words
        jp_data.append((j, norm, words))

    results = []
    for t_entry, t_norm, t_words in ten_data:
        for j_entry, j_norm, j_words in jp_data:
            if t_norm == j_norm:
                # Already caught by exact duplicate check
                continue

            common = t_words & j_words
            shorter_len = min(len(t_words), len(j_words))
            longer_len = max(len(t_words), len(j_words))
            shorter_overlap = len(common) / shorter_len if shorter_len else 0
            longer_overlap = len(common) / longer_len if longer_len else 0
            if (shorter_len >= 2
                    and len(common) >= 2
                    and shorter_overlap >= 0.75
                    and longer_overlap >= 0.60):
                results.append((t_entry, j_entry, common))

    return results


def entry_base_title(entry):
    """Extract the base title from a translation entry's filename.

    For [T-En] ROMs the selection log title is the Japanese base title,
    but the filename's title before (Japan) is the English translation name.
    """
    name = re.sub(r'\.(zip|7z|rar)$', '', entry['filename'], flags=re.IGNORECASE)
    name = re.sub(r'\s*\[T-En[^\]]*\].*$', '', name)
    name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
    return name.strip()


def check_regional_duplicates(entries):
    """Find near-miss title pairs from different regions that might be the same game.

    Only compares ROMs from different regions. Uses word overlap after
    removing stop words: requires >=75% overlap of the shorter title's
    significant words and at least 2 significant common words.
    Returns list of (entry_a, entry_b, common_words) tuples.
    """
    # Stop words — common words that don't indicate the same game
    stop_words = {
        'the', 'of', 'and', 'a', 'in', 'to', 'on', 'at', 'for', 'is', 'it',
        'no', 'de', 'des', 'du', 'le', 'la', 'les', 'un', 'une', 'et',
        'game', 'games', 'vol', 'volume', 'vs',
    }

    # Build (entry, normalized, significant_word_set) list
    data = []
    for entry in entries:
        norm = normalize_title(entry['title'])
        words = set(norm.split()) - stop_words
        if words:  # Skip entries with only stop words
            data.append((entry, norm, words))

    results = []
    seen = set()

    for i, (e_a, norm_a, words_a) in enumerate(data):
        for j in range(i + 1, len(data)):
            e_b, norm_b, words_b = data[j]

            # Skip identical normalized titles (caught by exact dup check)
            if norm_a == norm_b:
                continue

            # Only compare ROMs from different regions — same-region pairs
            # with similar names are sequels/spinoffs, not duplicates
            if e_a['region'] == e_b['region']:
                continue

            common = words_a & words_b
            shorter_len = min(len(words_a), len(words_b))
            longer_len = max(len(words_a), len(words_b))

            # Require >=75% overlap of BOTH titles' significant words,
            # not just the shorter. This prevents franchise matches like
            # "Classic NES Series - Bomberman" vs "Classic NES Series - Mappy"
            shorter_overlap = len(common) / shorter_len if shorter_len else 0
            longer_overlap = len(common) / longer_len if longer_len else 0
            if (shorter_len >= 2
                    and len(common) >= 2
                    and shorter_overlap >= 0.75
                    and longer_overlap >= 0.60):
                pair_key = tuple(sorted([norm_a, norm_b]))
                if pair_key not in seen:
                    seen.add(pair_key)
                    results.append((e_a, e_b, common))

    return results


def check_leaked_filters(entries):
    """Find ROMs that have exclusion flags set (should have been filtered).

    Re-parses each filename through parse_rom_filename() and checks for
    is_demo, is_compilation, is_beta, is_sample, is_proto, is_bios,
    is_pirate, is_rerelease.
    Returns list of (entry, [flag_names]) tuples.
    """
    flag_fields = [
        'is_demo', 'is_compilation', 'is_beta', 'is_sample',
        'is_proto', 'is_bios', 'is_pirate', 'is_rerelease',
    ]

    results = []
    for entry in entries:
        rom_info = parse_rom_filename(entry['filename'])
        flags = [f for f in flag_fields if getattr(rom_info, f, False)]
        if flags:
            results.append((entry, flags))

    return results


def check_non_english_localizations(entries):
    """Find non-English ROMs that likely duplicate an English ROM.

    Looks at Germany, France, Spain, Italy, Netherlands ROMs and checks
    for word overlap with English ROM titles.
    Returns list of (foreign_entry, english_entry, common_words) tuples.
    """
    non_english_regions = {'Germany', 'France', 'Spain', 'Italy', 'Netherlands',
                           'Sweden', 'Denmark', 'Norway', 'Portugal'}

    english_entries = []
    foreign_entries = []

    for entry in entries:
        if entry['region'] in non_english_regions:
            foreign_entries.append(entry)
        elif entry['region'] in ('USA', 'World', 'Europe', 'Australia', 'United Kingdom'):
            english_entries.append(entry)

    stop_words = {
        'the', 'of', 'and', 'a', 'in', 'to', 'on', 'at', 'for', 'is', 'it',
        'no', 'de', 'des', 'du', 'le', 'la', 'les', 'un', 'une', 'et',
        'game', 'games', 'vol', 'volume', 'vs',
    }

    # Pre-compute normalized data
    en_data = []
    for e in english_entries:
        norm = normalize_title(e['title'])
        words = set(norm.split()) - stop_words
        en_data.append((e, norm, words))

    results = []
    for f_entry in foreign_entries:
        f_norm = normalize_title(f_entry['title'])
        f_words = set(f_norm.split()) - stop_words

        if not f_words:
            continue

        best_match = None
        best_overlap = 0

        for e_entry, e_norm, e_words in en_data:
            if f_norm == e_norm:
                # Exact match — already caught by exact dup check, but still report
                best_match = (f_entry, e_entry, f_words | e_words)
                best_overlap = 1.0
                break

            if not e_words:
                continue

            common = f_words & e_words
            shorter_len = min(len(f_words), len(e_words))

            if shorter_len >= 2 and len(common) >= 2:
                overlap = len(common) / shorter_len
                if overlap >= 0.75 and overlap > best_overlap:
                    best_match = (f_entry, e_entry, common)
                    best_overlap = overlap

        if best_match:
            results.append(best_match)

    return results


def check_missing_roms(entries, sys_dir):
    """Compare selection log against actual files on disk.

    Returns (missing, unexpected) where:
        missing = filenames in log but not on disk
        unexpected = filenames on disk but not in log
    """
    log_filenames = {e['filename'] for e in entries}

    # Scan directory for ROM files (exclude metadata files)
    metadata_files = {'_selection_log.txt', '_crc_cache.json',
                      '_verification_report.txt', 'gamelist.xml'}
    disk_filenames = set()
    for f in sys_dir.iterdir():
        if f.is_file() and f.name not in metadata_files and not f.suffix == '.lpl':
            disk_filenames.add(f.name)

    missing = sorted(log_filenames - disk_filenames)
    unexpected = sorted(disk_filenames - log_filenames)

    return missing, unexpected


def check_missing_games(entries, dat_path):
    """Cross-reference selected ROMs against a DAT file.

    Parse the DAT, extract English retail games (USA/World/Europe, not
    beta/demo/sample/proto/bios), normalize titles, compare against
    selected ROM titles. Report games in DAT but not in selection.
    Returns list of dat_game_name strings.
    """
    dat_entries = parse_dat_file(Path(dat_path))

    # Build set of normalized titles from selected ROMs
    selected_titles = set()
    for entry in entries:
        selected_titles.add(normalize_title(entry['title']))

    # Filter DAT to English retail games
    missing = []
    seen_titles = set()

    for dat_entry in dat_entries.values():
        name = dat_entry.name

        # Skip non-English regions
        if dat_entry.region not in ('USA', 'World', 'Europe', 'Australia',
                                    'United Kingdom'):
            continue

        # Skip betas, demos, samples, protos, bios
        rom_info = parse_rom_filename(name + '.zip')
        if rom_info.is_beta or rom_info.is_demo or rom_info.is_sample:
            continue
        if rom_info.is_proto or rom_info.is_bios or rom_info.is_compilation:
            continue
        if rom_info.is_promo:
            continue

        # Normalize and check
        norm = normalize_title(rom_info.base_title)
        if norm in seen_titles:
            continue
        seen_titles.add(norm)

        if norm not in selected_titles:
            missing.append(name)

    return sorted(missing)


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def print_report(system, entries, exact_dups, ten_japan_dups, regional_dups,
                 leaked, non_english, missing_roms, unexpected_files,
                 missing_dat, dat_path):
    """Print a formatted audit report to stdout."""
    total_issues = (len(exact_dups) + len(ten_japan_dups) + len(regional_dups)
                    + len(leaked) + len(non_english) + len(missing_roms)
                    + len(unexpected_files) + len(missing_dat))

    # Header
    print()
    print('=' * 62)
    print(f"  ROM AUDIT REPORT -- {system.upper()}")
    print('=' * 62)

    # Summary stats
    region_counts = defaultdict(int)
    translation_count = 0
    for entry in entries:
        region_counts[entry['region']] += 1
        if entry['is_translation']:
            translation_count += 1

    print()
    print("SUMMARY")
    print(f"  Total ROMs selected: {len(entries):,}")

    region_parts = []
    for region in sorted(region_counts, key=lambda r: -region_counts[r]):
        region_parts.append(f"{region} {region_counts[region]:,}")
    print(f"  Regions: {', '.join(region_parts)}")
    print(f"  Translations: {translation_count}")

    # Check 1: Exact title duplicates
    print()
    print('-' * 62)
    print(f"1. EXACT TITLE DUPLICATES ({len(exact_dups)} found)")
    print('-' * 62)
    if exact_dups:
        for norm, group in exact_dups:
            print(f'  "{norm}"')
            for entry in group:
                print(f"    * {entry['filename']}")
        print()
        print("  Suggested mappings:")
        for norm, group in exact_dups:
            titles = set()
            for entry in group:
                t = normalize_title(entry['title'])
                titles.add(t)
            titles = sorted(titles)
            if len(titles) >= 2:
                # Map all variants to the first one
                for variant in titles[1:]:
                    if variant != titles[0]:
                        print(f'    "{variant}": "{titles[0]}"')
    else:
        print("  None")

    # Check 2: T-En + Japan duplicates
    print()
    print('-' * 62)
    print(f"2. T-EN + JAPAN DUPLICATES ({len(ten_japan_dups)} found)")
    print('-' * 62)
    if ten_japan_dups:
        for t_entry, j_entry, common in ten_japan_dups:
            print(f"  Common words: {{{', '.join(sorted(common))}}}")
            print(f"    T-En: {t_entry['filename']}")
            print(f"    Japan: {j_entry['filename']}")
    else:
        print("  None")

    # Check 3: Regional duplicates (near-miss)
    print()
    print('-' * 62)
    print(f"3. POTENTIAL REGIONAL DUPLICATES ({len(regional_dups)} found)")
    print('-' * 62)
    if regional_dups:
        for e_a, e_b, common in regional_dups:
            print(f"  Common words: {{{', '.join(sorted(common))}}}")
            print(f"    * {e_a['filename']}")
            print(f"    * {e_b['filename']}")
    else:
        print("  None")

    # Check 4: Leaked filters
    print()
    print('-' * 62)
    print(f"4. LEAKED FILTER CANDIDATES ({len(leaked)} found)")
    print('-' * 62)
    if leaked:
        for entry, flags in leaked:
            flag_str = ', '.join(f.replace('is_', '') for f in flags)
            print(f"  [{flag_str}] {entry['filename']}")
    else:
        print("  None")

    # Check 5: Non-English localizations
    print()
    print('-' * 62)
    print(f"5. NON-ENGLISH LOCALIZATIONS ({len(non_english)} found)")
    print('-' * 62)
    if non_english:
        for f_entry, e_entry, common in non_english:
            print(f"  {f_entry['filename']}")
            print(f"    English match: {e_entry['filename']}")
    else:
        print("  None")

    # Check 6: Missing ROMs (log vs disk)
    print()
    print('-' * 62)
    print(f"6. MISSING ROMS ({len(missing_roms)} in log but not on disk"
          f", {len(unexpected_files)} on disk but not in log)")
    print('-' * 62)
    if missing_roms:
        print("  In selection log but not on disk:")
        for name in missing_roms[:30]:
            print(f"    - {name}")
        if len(missing_roms) > 30:
            print(f"    ... and {len(missing_roms) - 30} more")
    if unexpected_files:
        print("  On disk but not in selection log:")
        for name in unexpected_files[:30]:
            print(f"    + {name}")
        if len(unexpected_files) > 30:
            print(f"    ... and {len(unexpected_files) - 30} more")
    if not missing_roms and not unexpected_files:
        print("  None")

    # Check 7: Missing games (DAT cross-reference)
    print()
    print('-' * 62)
    if dat_path:
        print(f"7. MISSING GAMES FROM DAT ({len(missing_dat)} found)")
    else:
        print("7. MISSING GAMES FROM DAT (skipped, no --dat provided)")
    print('-' * 62)
    if dat_path and missing_dat:
        for name in missing_dat[:50]:  # Cap display at 50
            print(f"  {name}")
        if len(missing_dat) > 50:
            print(f"  ... and {len(missing_dat) - 50} more")
    elif dat_path:
        print("  None")

    # Totals — each exact dup group has N roms, N-1 are removable
    removable_from_dups = sum(len(group) - 1 for _, group in exact_dups)
    estimated_removals = removable_from_dups + len(ten_japan_dups) + len(leaked) + len(non_english)

    print()
    print('-' * 62)
    print("TOTALS")
    print('-' * 62)
    print(f"  Issues found: {total_issues}")
    print(f"  Estimated ROMs to remove after fixes: ~{estimated_removals}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def detect_system_dirs(path):
    """Given a path, return a list of (system_name, dir_path) tuples.

    If the path contains _selection_log.txt, treat it as a single system dir.
    Otherwise, scan subdirectories for selection logs.
    """
    path = Path(path)
    results = []

    if (path / '_selection_log.txt').is_file():
        results.append((path.name, path))
    else:
        for child in sorted(path.iterdir()):
            if child.is_dir() and (child / '_selection_log.txt').is_file():
                results.append((child.name, child))

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Audit refined ROM collections for duplicates and issues',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python tools/audit.py refined/gba/                         # Audit one system
  python tools/audit.py refined/                             # Audit all systems
  python tools/audit.py refined/gba/ --dat dat_files/gba.dat # With missing-game check
""",
    )
    parser.add_argument('path', help='Path to a refined system directory or parent directory')
    parser.add_argument('--dat', help='DAT file for missing-game cross-reference')
    args = parser.parse_args()

    system_dirs = detect_system_dirs(args.path)

    if not system_dirs:
        print(f"No _selection_log.txt found in {args.path}", file=sys.stderr)
        sys.exit(1)

    grand_total_issues = 0
    grand_total_removals = 0

    for system, sys_dir in system_dirs:
        log_path = sys_dir / '_selection_log.txt'
        entries = parse_selection_log(log_path)

        if not entries:
            print(f"\n  {system}: no selected ROMs found in log, skipping")
            continue

        # Run all checks
        exact_dups = check_exact_duplicates(entries)
        ten_japan_dups = check_ten_japan_duplicates(entries)
        regional_dups = check_regional_duplicates(entries)
        leaked = check_leaked_filters(entries)
        non_english = check_non_english_localizations(entries)
        missing_roms, unexpected_files = check_missing_roms(entries, sys_dir)

        missing_dat = []
        dat_path = args.dat
        if dat_path:
            missing_dat = check_missing_games(entries, dat_path)

        # Print report
        print_report(system, entries, exact_dups, ten_japan_dups, regional_dups,
                     leaked, non_english, missing_roms, unexpected_files,
                     missing_dat, dat_path)

        # Accumulate grand totals
        total_issues = (len(exact_dups) + len(ten_japan_dups) + len(regional_dups)
                        + len(leaked) + len(non_english) + len(missing_roms)
                        + len(unexpected_files) + len(missing_dat))
        removable = (sum(len(g) - 1 for _, g in exact_dups)
                     + len(ten_japan_dups) + len(leaked) + len(non_english))
        grand_total_issues += total_issues
        grand_total_removals += removable

    if len(system_dirs) > 1:
        print('=' * 62)
        print(f"  GRAND TOTAL ACROSS {len(system_dirs)} SYSTEMS")
        print('=' * 62)
        print(f"  Issues found: {grand_total_issues}")
        print(f"  Estimated ROMs to remove: ~{grand_total_removals}")
        print()


if __name__ == '__main__':
    main()
