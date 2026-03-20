# Title Mapping Analyzer — Design Document

## Goal

Systematically improve title mappings across all 144 supported systems by analyzing No-Intro, Redump, and T-En DAT files. Automatically add high-confidence mappings, flag low-confidence candidates for review, validate existing mappings, and generate regression tests.

## Tool

`tools/analyze_title_mappings.py` — standalone script, no new dependencies.

Run: `python tools/analyze_title_mappings.py`
Force re-download: `python tools/analyze_title_mappings.py --fresh`

## Data Sources

- **No-Intro DATs** (cartridge systems) — via existing `download_libretro_dat()`
- **Redump DATs** (disc systems) — same function, auto-selected for disc-based systems
- **T-En DATs** (fan translations) — via existing `fetch_ten_dat_listing()` / download functions
- Reuses existing DAT cache in `dat_files/`. Downloads in parallel (8 workers).
- Skips arcade systems (MAME/FBNeo/CPS) — those use `mame.py` filtering, not title mappings.

## Detection Algorithm

### Method 1 — T-En Cross-Reference (highest confidence, auto-add)

For each T-En entry (e.g., `"Fire Emblem - Monshou no Nazo (Japan) [T-En]"`), extract the Japanese base title. Look for a matching USA/Europe entry in the same system's No-Intro/Redump DAT. If the normalized titles differ, add the mapping.

### Method 2 — Size-Matched Regional Variants (high confidence, auto-add)

Within a single system DAT, find entries with:
- Identical or near-identical ROM sizes (within ~1KB for header differences)
- Different regions (Japan vs USA/Europe)
- Normalized titles that don't already match

Exact size match = auto-add. Near-match = auto-add with slightly lower confidence.

### Method 3 — Fuzzy Title Matching (low confidence, review only)

For remaining ungrouped entries, use `difflib.SequenceMatcher` to find similar titles. These go into the review report, not auto-added.

## Validation of Existing Mappings

For each mapping in `title_mappings.json`:

1. **Orphaned:** Variant title not found in any DAT → remove automatically
2. **Redundant:** Normalization already handles this without the mapping → remove automatically
3. **Incorrect direction:** Canonical title not found in any DAT → flag for review

## Output

### Direct modifications
- **`data/title_mappings.json`** — new mappings added, orphaned/redundant removed, `_meta.updated` date updated

### Generated files
- **`tools/mapping_review.txt`** — low-confidence candidates with context (titles, regions, similarity scores, ROM sizes)

### Generated tests
- **`tests/test_selection.py`** — appends regression tests verifying that each new mapping causes two specific ROM filenames to normalize to the same title

### Stdout summary
- Per-system stats (entries parsed, groups formed, new mappings added)
- Validation results (orphaned/redundant removed, flagged issues)
- Low-confidence candidate count
- Total new mappings added

## Performance

- Reuses existing DAT cache; `--fresh` to force re-download
- Parallel DAT downloads (8 workers)
- Expected: ~2-3 min first run, <30s with cached DATs

## Files Touched

- Creates: `tools/analyze_title_mappings.py`
- Modifies: `data/title_mappings.json` (when run)
- Modifies: `tests/test_selection.py` (when run, appends tests)
- Creates: `tools/mapping_review.txt` (when run)
