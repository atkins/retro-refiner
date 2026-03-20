# Title Mapping Analyzer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a tool that analyzes DAT files across all supported systems to find missing title mappings, auto-add high-confidence ones, validate existing mappings, and generate regression tests.

**Architecture:** A standalone script (`tools/analyze_title_mappings.py`) that downloads No-Intro/Redump/T-En DATs using existing `dat.py` functions, parses all entries, runs `normalize_title()` to find grouping gaps, then uses three detection methods (T-En cross-reference, size-matched regional variants, fuzzy matching) to find and add mappings. Existing mappings are validated and orphaned/redundant ones are removed.

**Tech Stack:** Python 3.10+, existing `retro_refiner.dat` and `retro_refiner.filter` modules, `difflib.SequenceMatcher` for fuzzy matching, `concurrent.futures.ThreadPoolExecutor` for parallel downloads.

---

### Task 1: Create the tool scaffold with DAT downloading

**Files:**
- Create: `tools/analyze_title_mappings.py`

**Step 1: Create the tools directory and main script**

Create `tools/analyze_title_mappings.py` with:
- Argument parsing (`--fresh` flag to force re-download)
- A function `download_all_dats(dat_dir, force)` that:
  - Gets the list of all systems from `data/systems.json` via `load_system_data()`
  - Skips arcade systems: `mame`, `fbneo`, `fba`, `arcade`, `cps1`, `cps2`, `cps3`, `naomi`, `naomi2`, `atomiswave`, `model2`, `model3`, `neogeo`, `daphne`
  - Downloads No-Intro/Redump DATs using `download_libretro_dat(system, dat_dir, force=force)` — 8-thread pool
  - Downloads T-En DATs using `download_ten_dat(system, dat_dir, force=force, listing_cache=listing)` — sequential (Archive.org rate limits)
  - Prints progress per system
  - Returns dict of `{system: [dat_path, ...]}` (main DAT + T-En DAT if available)

```python
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
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add project root to path so we can import retro_refiner
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retro_refiner.dat import (
    download_libretro_dat, download_ten_dat,
    fetch_ten_dat_listing, parse_dat_file,
    normalize_title, load_title_mappings,
    reset_title_mappings_cache,
)
from retro_refiner.filter import parse_rom_filename
from retro_refiner.systems import load_system_data

SKIP_SYSTEMS = frozenset({
    'mame', 'fbneo', 'fba', 'arcade',
    'cps1', 'cps2', 'cps3',
    'naomi', 'naomi2', 'atomiswave',
    'model2', 'model3', 'neogeo', 'daphne',
})


def download_all_dats(dat_dir: Path, force: bool = False):
    """Download all DATs for every supported system.

    Returns dict of {system: [dat_paths]}.
    """
    sdata = load_system_data()
    all_systems = sorted(
        s for s in sdata.libretro_dat_systems
        if s not in SKIP_SYSTEMS
    )

    result = {}
    failed = []

    # Download No-Intro/Redump DATs in parallel
    print(f"Downloading DATs for {len(all_systems)} systems...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(download_libretro_dat, sys, dat_dir, force): sys
            for sys in all_systems
        }
        for future in as_completed(futures):
            sys_code = futures[future]
            dat_path = future.result()
            if dat_path:
                result.setdefault(sys_code, []).append(dat_path)
            else:
                failed.append(sys_code)

    # Download T-En DATs (sequential — Archive.org rate limits)
    print("Fetching T-En DAT listing...")
    listing = fetch_ten_dat_listing()
    ten_systems = [s for s in all_systems if s not in failed]
    for sys_code in ten_systems:
        ten_path = download_ten_dat(
            sys_code, dat_dir, force=force, listing_cache=listing)
        if ten_path:
            result.setdefault(sys_code, []).append(ten_path)

    downloaded = len(result)
    print(f"Downloaded DATs for {downloaded} systems "
          f"({len(failed)} failed)")
    if failed:
        print(f"  Failed: {', '.join(sorted(failed))}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Analyze DAT files for missing title mappings')
    parser.add_argument('--fresh', action='store_true',
                        help='Force re-download of all DATs')
    args = parser.parse_args()

    dat_dir = Path(__file__).resolve().parent.parent / 'dat_files'
    system_dats = download_all_dats(dat_dir, force=args.fresh)

    print(f"\nReady to analyze {len(system_dats)} systems")


if __name__ == '__main__':
    main()
```

**Step 2: Test the script runs without errors**

Run: `python tools/analyze_title_mappings.py`
Expected: Downloads DATs (or uses cache), prints summary. No errors.

**Step 3: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "feat: add title mapping analyzer scaffold with DAT downloading"
```

---

### Task 2: Parse DATs and build title groups per system

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Add the `parse_system_entries` function**

This parses all DAT files for a system and returns a list of `(name, base_title, normalized_title, region, size, is_ten)` tuples.

```python
def parse_system_entries(system, dat_paths):
    """Parse all DAT entries for a system.

    Returns list of (name, base_title, normalized, region, size, is_ten) tuples.
    """
    entries = []
    for dat_path in dat_paths:
        is_ten = '_t-en' in dat_path.name
        dat_entries = parse_dat_file(dat_path)
        for crc, entry in dat_entries.items():
            rom_info = parse_rom_filename(entry.name + '.zip')
            # Skip betas, demos, protos, bios, compilations, hacks
            if (rom_info.is_beta or rom_info.is_demo or rom_info.is_proto
                    or rom_info.is_bios or rom_info.is_compilation
                    or rom_info.has_hacks or rom_info.is_pirate
                    or rom_info.is_sample):
                continue
            normalized = normalize_title(rom_info.base_title)
            entries.append((
                entry.name,
                rom_info.base_title,
                normalized,
                entry.region,
                entry.size,
                is_ten,
            ))
    return entries
```

**Step 2: Add the `build_title_groups` function**

Groups entries by normalized title and identifies ungrouped regional variants — entries from different regions that didn't merge.

```python
from collections import defaultdict

def build_title_groups(entries):
    """Group entries by normalized title.

    Returns:
        groups: dict of normalized_title -> list of entries
        ungrouped_japan: entries with Japan region not in any multi-region group
        ungrouped_west: entries with USA/Europe region not in any multi-region group
    """
    groups = defaultdict(list)
    for entry in entries:
        groups[entry[2]].append(entry)  # entry[2] = normalized title

    # Find Japan-only and West-only groups
    ungrouped_japan = []
    ungrouped_west = []
    for normalized, group_entries in groups.items():
        regions = {e[3] for e in group_entries}  # e[3] = region
        has_japan = 'Japan' in regions or 'Asia' in regions
        has_west = bool(regions & {'USA', 'Europe', 'World', 'Australia'})
        if has_japan and not has_west:
            ungrouped_japan.extend(group_entries)
        elif has_west and not has_japan:
            ungrouped_west.extend(group_entries)

    return groups, ungrouped_japan, ungrouped_west
```

**Step 3: Wire into main() for a dry-run report**

Add to `main()`:

```python
    total_entries = 0
    total_groups = 0
    for system in sorted(system_dats):
        dat_paths = system_dats[system]
        entries = parse_system_entries(system, dat_paths)
        groups, jp_only, west_only = build_title_groups(entries)
        total_entries += len(entries)
        total_groups += len(groups)
        if jp_only or west_only:
            print(f"  {system}: {len(entries)} entries, "
                  f"{len(groups)} groups, "
                  f"{len(jp_only)} JP-only, "
                  f"{len(west_only)} West-only")

    print(f"\nTotal: {total_entries} entries, {total_groups} groups")
```

**Step 4: Test**

Run: `python tools/analyze_title_mappings.py`
Expected: Prints per-system stats showing JP-only and West-only counts.

**Step 5: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "feat: parse DATs and build title groups per system"
```

---

### Task 3: Implement Method 1 — T-En cross-reference detection

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Add the `find_ten_mappings` function**

For each T-En entry, find its corresponding official title in the No-Intro/Redump entries.

```python
def find_ten_mappings(entries):
    """Find mappings by cross-referencing T-En entries with official DATs.

    For each T-En entry (fan translation), look for a non-T-En entry
    whose base title differs after normalization. If the T-En entry's
    Japanese title normalizes differently from the English equivalent,
    that's a missing mapping.

    Returns list of (variant_normalized, canonical_normalized,
                     variant_name, canonical_name, method) tuples.
    """
    ten_entries = [e for e in entries if e[5]]       # is_ten=True
    official_entries = [e for e in entries if not e[5]]

    # Build lookup: normalized_title -> list of official entries
    official_by_norm = defaultdict(list)
    for entry in official_entries:
        official_by_norm[entry[2]].append(entry)

    # Build lookup: size -> list of official entries
    official_by_size = defaultdict(list)
    for entry in official_entries:
        official_by_size[entry[4]].append(entry)

    mappings = []
    for ten_entry in ten_entries:
        ten_norm = ten_entry[2]   # normalized title
        ten_size = ten_entry[4]   # ROM size

        # Already groups with an official entry?
        if ten_norm in official_by_norm:
            continue

        # Try size match to find the corresponding official entry
        size_matches = official_by_size.get(ten_size, [])
        if not size_matches:
            # Try near-size (within 1KB for header differences)
            for delta in range(1, 1025):
                size_matches = (official_by_size.get(ten_size + delta, [])
                                + official_by_size.get(ten_size - delta, []))
                if size_matches:
                    break

        if size_matches:
            # Pick the best match — prefer USA, then Europe, then World
            best = None
            for candidate in size_matches:
                if candidate[3] in ('USA', 'World', 'Europe'):
                    if best is None or (
                        candidate[3] == 'USA' and best[3] != 'USA'):
                        best = candidate
            if best is None:
                best = size_matches[0]

            if best[2] != ten_norm:  # normalized titles differ
                mappings.append((
                    ten_norm, best[2],
                    ten_entry[0], best[0],
                    'ten_crossref',
                ))

    return mappings
```

**Step 2: Wire into main()**

Collect mappings across all systems:

```python
    all_mappings = []
    for system in sorted(system_dats):
        dat_paths = system_dats[system]
        entries = parse_system_entries(system, dat_paths)

        ten_maps = find_ten_mappings(entries)
        for m in ten_maps:
            all_mappings.append((system, *m))

    print(f"\nMethod 1 (T-En): {len(all_mappings)} candidate mappings")
```

**Step 3: Test**

Run: `python tools/analyze_title_mappings.py`
Expected: Reports T-En candidate mappings found.

**Step 4: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "feat: implement T-En cross-reference detection (method 1)"
```

---

### Task 4: Implement Method 2 — size-matched regional variants

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Add the `find_size_matched_mappings` function**

Within official DAT entries only, find Japan entries whose ROM size exactly matches a USA/Europe entry but whose normalized titles differ.

```python
def find_size_matched_mappings(entries):
    """Find mappings by matching ROM sizes across regions.

    When a Japan entry has the exact same ROM size as a USA/Europe entry,
    they're very likely the same game. If normalized titles differ,
    that's a missing mapping.

    Returns list of (variant_normalized, canonical_normalized,
                     variant_name, canonical_name, method) tuples.
    """
    official = [e for e in entries if not e[5]]  # not T-En

    japan_entries = [e for e in official
                     if e[3] in ('Japan', 'Asia', 'Korea')]
    west_entries = [e for e in official
                    if e[3] in ('USA', 'Europe', 'World', 'Australia')]

    if not japan_entries or not west_entries:
        return []

    # Build size -> entries lookup for western entries
    west_by_size = defaultdict(list)
    for entry in west_entries:
        west_by_size[entry[4]].append(entry)

    mappings = []
    seen = set()

    for jp_entry in japan_entries:
        jp_norm = jp_entry[2]

        # Already has a western match via normalization?
        if any(w[2] == jp_norm for w in west_entries):
            continue

        # Check exact size match
        size_matches = west_by_size.get(jp_entry[4], [])
        if not size_matches:
            continue

        # Pick best western match
        best = None
        for candidate in size_matches:
            if candidate[2] == jp_norm:
                continue  # already matches
            if best is None or (
                candidate[3] == 'USA' and best[3] != 'USA'):
                best = candidate

        if best and best[2] != jp_norm:
            key = (jp_norm, best[2])
            if key not in seen:
                seen.add(key)
                mappings.append((
                    jp_norm, best[2],
                    jp_entry[0], best[0],
                    'size_match',
                ))

    return mappings
```

**Step 2: Wire into the main loop**

Add method 2 results alongside method 1 in the per-system loop:

```python
        size_maps = find_size_matched_mappings(entries)
        for m in size_maps:
            all_mappings.append((system, *m))
```

And update the summary:

```python
    ten_count = sum(1 for m in all_mappings if m[5] == 'ten_crossref')
    size_count = sum(1 for m in all_mappings if m[5] == 'size_match')
    print(f"\nMethod 1 (T-En): {ten_count} mappings")
    print(f"Method 2 (size): {size_count} mappings")
```

**Step 3: Test**

Run: `python tools/analyze_title_mappings.py`
Expected: Reports both T-En and size-match candidate mappings.

**Step 4: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "feat: implement size-matched regional variant detection (method 2)"
```

---

### Task 5: Implement Method 3 — fuzzy title matching

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Add the `find_fuzzy_mappings` function**

For remaining ungrouped Japan entries that weren't caught by methods 1-2, use string similarity to find near-matches.

```python
from difflib import SequenceMatcher

def find_fuzzy_mappings(entries, existing_mappings_set):
    """Find potential mappings via fuzzy string matching.

    These are LOW confidence — written to review file only, not auto-added.

    Args:
        entries: All parsed entries for a system.
        existing_mappings_set: Set of (variant, canonical) already found
            by methods 1-2 to avoid duplicates.

    Returns list of (variant_normalized, canonical_normalized,
                     variant_name, canonical_name, method, score) tuples.
    """
    official = [e for e in entries if not e[5]]

    japan_entries = [e for e in official
                     if e[3] in ('Japan', 'Asia', 'Korea')]
    west_entries = [e for e in official
                    if e[3] in ('USA', 'Europe', 'World', 'Australia')]

    if not japan_entries or not west_entries:
        return []

    # Only consider Japan entries not already mapped
    mapped_variants = {m[0] for m in existing_mappings_set}
    unmapped_jp = [e for e in japan_entries if e[2] not in mapped_variants]

    # Also skip Japan entries that already group with western entries
    west_norms = {e[2] for e in west_entries}
    unmapped_jp = [e for e in unmapped_jp if e[2] not in west_norms]

    # Build unique western normalized titles
    west_unique = {}
    for entry in west_entries:
        if entry[2] not in west_unique:
            west_unique[entry[2]] = entry

    candidates = []
    for jp_entry in unmapped_jp:
        jp_norm = jp_entry[2]
        best_score = 0
        best_match = None

        for west_norm, west_entry in west_unique.items():
            score = SequenceMatcher(
                None, jp_norm, west_norm).ratio()
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = west_entry

        if best_match and best_score >= 0.6:
            candidates.append((
                jp_norm, best_match[2],
                jp_entry[0], best_match[0],
                'fuzzy',
                best_score,
            ))

    return candidates
```

**Step 2: Wire into main loop**

Collect fuzzy candidates separately (they won't be auto-added):

```python
    all_fuzzy = []
    for system in sorted(system_dats):
        # ... existing code ...

        # Build set of already-found mappings for this system
        system_found = {(m[1], m[2]) for m in all_mappings if m[0] == system}
        fuzzy = find_fuzzy_mappings(entries, system_found)
        for f in fuzzy:
            all_fuzzy.append((system, *f))
```

**Step 3: Test**

Run: `python tools/analyze_title_mappings.py`
Expected: Reports fuzzy candidates with scores.

**Step 4: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "feat: implement fuzzy title matching for review candidates (method 3)"
```

---

### Task 6: Validate existing mappings

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Add the `validate_existing_mappings` function**

```python
def validate_existing_mappings(all_normalized_titles):
    """Validate existing title mappings against DAT data.

    Args:
        all_normalized_titles: Set of all normalized titles found in DATs.

    Returns:
        orphaned: list of (variant, canonical, category) — variant not in any DAT
        redundant: list of (variant, canonical, category) — normalization handles it
        bad_canonical: list of (variant, canonical, category) — canonical not in DATs
    """
    mappings_path = (Path(__file__).resolve().parent.parent
                     / 'data' / 'title_mappings.json')
    with open(mappings_path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)

    orphaned = []
    redundant = []
    bad_canonical = []

    for category, entries in data.items():
        if category.startswith('_') or not isinstance(entries, dict):
            continue
        for variant, canonical in entries.items():
            if variant not in all_normalized_titles:
                orphaned.append((variant, canonical, category))
            elif canonical not in all_normalized_titles:
                bad_canonical.append((variant, canonical, category))
            # Check if normalization without this mapping already works
            # (i.e., this mapping is redundant)

    # For redundancy check, we need to test normalization without
    # each mapping. This is expensive, so we do a simpler check:
    # if variant == canonical after normalization, it's redundant.
    for category, entries in data.items():
        if category.startswith('_') or not isinstance(entries, dict):
            continue
        for variant, canonical in entries.items():
            if variant == canonical:
                redundant.append((variant, canonical, category))

    return orphaned, redundant, bad_canonical
```

**Step 2: Wire into main()**

After the analysis loop, validate and report:

```python
    # Collect all normalized titles from all systems
    all_normalized = set()
    for system in sorted(system_dats):
        dat_paths = system_dats[system]
        entries = parse_system_entries(system, dat_paths)
        for entry in entries:
            all_normalized.add(entry[2])

    orphaned, redundant, bad_canonical = validate_existing_mappings(
        all_normalized)

    print(f"\nValidation:")
    print(f"  Orphaned (variant not in DATs): {len(orphaned)}")
    print(f"  Redundant (variant == canonical): {len(redundant)}")
    print(f"  Bad canonical (target not in DATs): {len(bad_canonical)}")
```

**Step 3: Test**

Run: `python tools/analyze_title_mappings.py`
Expected: Reports validation findings.

**Step 4: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "feat: validate existing title mappings against DAT data"
```

---

### Task 7: Write mappings to title_mappings.json and generate review file

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Add the `apply_mappings` function**

Writes high-confidence mappings (methods 1 and 2) to `title_mappings.json`, removes orphaned/redundant entries, and writes low-confidence candidates to `tools/mapping_review.txt`.

```python
from datetime import date

def apply_mappings(new_mappings, orphaned, redundant):
    """Apply high-confidence mappings to title_mappings.json.

    Args:
        new_mappings: list of (system, variant, canonical, variant_name,
                      canonical_name, method) tuples
        orphaned: list of (variant, canonical, category) to remove
        redundant: list of (variant, canonical, category) to remove

    Returns count of mappings added and removed.
    """
    mappings_path = (Path(__file__).resolve().parent.parent
                     / 'data' / 'title_mappings.json')
    with open(mappings_path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)

    # Load existing flat mappings to avoid duplicates
    existing_flat = {}
    for cat, entries in data.items():
        if cat.startswith('_') or not isinstance(entries, dict):
            continue
        existing_flat.update(entries)

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
        # Remove empty categories
        if not data[category]:
            del data[category]

    # Add new mappings, grouped by system category
    added = 0
    for system, variant, canonical, _, _, method in new_mappings:
        if variant in existing_flat:
            continue  # already mapped
        if variant == canonical:
            continue  # no-op mapping

        # Determine category name
        if method == 'ten_crossref':
            cat_name = f'translations_{system}'
        else:
            cat_name = f'regional_{system}'

        if cat_name not in data:
            data[cat_name] = {}

        data[cat_name][variant] = canonical
        existing_flat[variant] = canonical
        added += 1

    # Update metadata
    if '_meta' in data:
        data['_meta']['updated'] = str(date.today())

    # Write back (sorted categories, sorted keys within each)
    sorted_data = {}
    if '_meta' in data:
        sorted_data['_meta'] = data['_meta']
    for key in sorted(k for k in data if k != '_meta'):
        sorted_data[key] = dict(sorted(data[key].items()))

    with open(mappings_path, 'w', encoding='utf-8') as fh:
        json.dump(sorted_data, fh, indent=2, ensure_ascii=False)
        fh.write('\n')

    return added, removed


def write_review_file(fuzzy_candidates):
    """Write low-confidence candidates to review file."""
    review_path = (Path(__file__).resolve().parent
                   / 'mapping_review.txt')

    with open(review_path, 'w', encoding='utf-8') as fh:
        fh.write("# Title Mapping Review Candidates\n")
        fh.write(f"# Generated: {date.today()}\n")
        fh.write("# These are low-confidence fuzzy matches.\n")
        fh.write("# Review and add good ones to "
                 "data/title_mappings.json manually.\n\n")

        for system, variant, canonical, var_name, can_name, method, score in fuzzy_candidates:
            fh.write(f"[{system}] score={score:.2f}\n")
            fh.write(f"  JP: {var_name}\n")
            fh.write(f"      normalized: {variant}\n")
            fh.write(f"  EN: {can_name}\n")
            fh.write(f"      normalized: {canonical}\n\n")

    print(f"Review file written: {review_path}")
    print(f"  {len(fuzzy_candidates)} candidates to review")
```

**Step 2: Wire into main()**

After all analysis is done:

```python
    added, removed = apply_mappings(all_mappings, orphaned, redundant)
    write_review_file(all_fuzzy)

    print(f"\nResults:")
    print(f"  Mappings added: {added}")
    print(f"  Mappings removed: {removed}")
    print(f"  Fuzzy candidates for review: {len(all_fuzzy)}")
```

**Step 3: Test**

Run: `python tools/analyze_title_mappings.py`
Expected: Modifies `title_mappings.json`, creates `tools/mapping_review.txt`, prints summary.

Verify: `git diff data/title_mappings.json` shows new mappings added.

**Step 4: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "feat: write high-confidence mappings and generate review file"
```

---

### Task 8: Generate regression tests

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Add the `generate_tests` function**

For each new mapping added, generate a test that verifies two ROM filenames normalize to the same title.

```python
def generate_tests(new_mappings):
    """Append regression tests to test_selection.py for new mappings.

    Each test verifies that a variant ROM filename and its canonical
    equivalent normalize to the same title via normalize_title().

    Args:
        new_mappings: list of (system, variant, canonical, variant_name,
                      canonical_name, method) tuples that were actually added.

    Returns count of tests added.
    """
    if not new_mappings:
        return 0

    test_path = (Path(__file__).resolve().parent.parent
                 / 'tests' / 'test_selection.py')

    # Read existing test file
    content = test_path.read_text(encoding='utf-8')

    # Find the insertion point — before the last function call block
    # in main(). We look for "def main():" and add test function calls there.
    # Actually, we'll add a new test function and register it.

    # Build test function
    test_lines = []
    test_lines.append("")
    test_lines.append("")
    test_lines.append("def test_generated_title_mappings():")
    test_lines.append('    """Auto-generated tests for title mappings '
                      'from analyze_title_mappings.py."""')
    test_lines.append("    from retro_refiner.dat import normalize_title")
    test_lines.append("")

    count = 0
    seen = set()
    for system, variant, canonical, var_name, can_name, method in new_mappings:
        key = (variant, canonical)
        if key in seen:
            continue
        seen.add(key)
        # Escape quotes in names
        var_esc = var_name.replace("'", "\\'")
        can_esc = can_name.replace("'", "\\'")
        test_lines.append(f"    # {system}: {method}")
        test_lines.append(
            f"    result.assert_equal(")
        test_lines.append(
            f"        normalize_title(parse_rom_filename('{var_esc}.zip').base_title),")
        test_lines.append(
            f"        normalize_title(parse_rom_filename('{can_esc}.zip').base_title),")
        test_lines.append(
            f"        '{var_esc} should map to {can_esc}')")
        test_lines.append("")
        count += 1

    if count == 0:
        return 0

    # Find where to insert — before "if __name__"
    marker = "if __name__ == '__main__':"
    idx = content.rfind(marker)
    if idx == -1:
        print("WARNING: Could not find insertion point in test file")
        return 0

    # Also need to register the test call in main()
    # Find "test_backward_compat_config()" to insert after
    call_marker = "    test_backward_compat_config()"
    call_idx = content.rfind(call_marker)

    if call_idx == -1:
        print("WARNING: Could not find test registration point")
        return 0

    # Insert test function before __main__ block
    test_func = '\n'.join(test_lines) + '\n\n\n'
    new_content = content[:idx] + test_func + content[idx:]

    # Insert test call after backward_compat_config call
    call_line = "\n    test_generated_title_mappings()"
    call_insert_pos = call_idx + len(call_marker)
    # Recalculate position after previous insertion
    offset = len(test_func)
    new_content = (new_content[:call_insert_pos + offset]
                   + call_line
                   + new_content[call_insert_pos + offset:])

    test_path.write_text(new_content, encoding='utf-8')

    return count
```

**Step 2: Wire into main()**

After applying mappings, filter to only actually-added mappings and generate tests:

```python
    # Generate tests for mappings that were actually added
    # Re-read the mappings file to confirm what's there
    reset_title_mappings_cache()
    current_mappings = load_title_mappings()
    actually_added = [
        m for m in all_mappings
        if m[1] in current_mappings and current_mappings[m[1]] == m[2]
    ]
    test_count = generate_tests(actually_added)
    print(f"  Tests generated: {test_count}")
```

**Step 3: Test**

Run: `python tools/analyze_title_mappings.py`
Then: `python tests/test_selection.py`
Expected: All tests pass including new generated ones.

**Step 4: Commit**

```bash
git add tools/analyze_title_mappings.py tests/test_selection.py data/title_mappings.json tools/mapping_review.txt
git commit -m "feat: complete title mapping analyzer with test generation"
```

---

### Task 9: Refactor main() for clean flow and final polish

**Files:**
- Modify: `tools/analyze_title_mappings.py`

**Step 1: Refactor main() into clean sequential flow**

The main function should follow this order:
1. Download DATs
2. Parse all systems and collect entries (cache parsed results)
3. Run method 1 (T-En) per system
4. Run method 2 (size match) per system
5. Run method 3 (fuzzy) per system
6. Validate existing mappings
7. Apply mappings to JSON
8. Write review file
9. Generate tests
10. Print final summary

Make sure `parse_system_entries` is only called once per system (cache the results).

**Step 2: Add deduplication of mappings**

Before applying, deduplicate: if methods 1 and 2 both found the same mapping, keep only one. Also filter out any mapping where the variant already exists in the current title_mappings.json.

**Step 3: Run the full tool and verify**

Run: `python tools/analyze_title_mappings.py`
Then: `python tests/test_selection.py`
Then: `python -m pylint tools/analyze_title_mappings.py`
Expected: Tool runs end-to-end, all tests pass, lint clean.

**Step 4: Commit**

```bash
git add tools/analyze_title_mappings.py
git commit -m "refactor: clean up analyzer main flow and deduplicate mappings"
```

---

### Task 10: Lint and final verification

**Step 1: Run pylint on the tool**

Run: `python -m pylint tools/analyze_title_mappings.py`
Expected: Clean (or document any necessary disables)

**Step 2: Run all tests**

Run: `python tests/test_selection.py && python tests/test_v2_config.py && python tests/test_v2_cli.py && python tests/test_v2_integration.py && python tests/test_v2_paths.py && python tests/test_v2_systems.py`
Expected: All pass

**Step 3: Run the tool one final time on clean state**

```bash
git stash  # stash any generated changes
python tools/analyze_title_mappings.py
python tests/test_selection.py
```
Expected: Tool runs, mappings added, tests generated, all tests pass.

**Step 4: Commit everything**

```bash
git add tools/ data/title_mappings.json tests/test_selection.py
git commit -m "feat: title mapping analyzer — auto-detect and test regional title variants"
```

---

## Key Design Decisions

1. **Three-tier confidence:** T-En cross-ref (auto-add) > size match (auto-add) > fuzzy (review only). This prevents false positives from fuzzy matching while capturing the strongest signals automatically.

2. **Arcade systems skipped:** MAME/FBNeo use `mame.py` filtering with catver.ini, not title mappings. Including them would generate noise.

3. **Category naming:** New mappings go into `translations_{system}` (for T-En matches) or `regional_{system}` (for size matches), following the existing convention.

4. **Tests use actual ROM filenames from DATs:** This tests the full pipeline (parse_rom_filename → normalize_title → mapping lookup), not just the mapping dict.

5. **Orphaned/redundant cleanup is automatic:** These are safe to remove — orphaned means the ROM doesn't exist in any DAT, redundant means normalization handles it without the mapping.
