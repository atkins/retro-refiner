# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Retro-Refiner is a zero-dependency Python script (~8,400 lines in a single file `retro-refiner.py`) that filters ROM collections to select the best English version of each game. It supports 144 systems, local and network sources, and multiple arcade formats (MAME, FBNeo, TeknoParrot).

## Commands

### Run tests
```bash
python tests/test_selection.py
```
Note: `pytest` is not installed. Tests use `unittest` and are run directly.

### Lint
```bash
python -m pylint retro-refiner.py
```
CI runs pylint across Python 3.8/3.9/3.10 (see `.github/workflows/pylint.yml`). The `.pylintrc` disables complexity checks since this is a large single-file script by design. Current score: **10.00/10** — avoid introducing new warnings.

### Dry run (preview only)
```bash
python retro-refiner.py -s /path/to/roms
```

### Commit mode (actually transfer files)
```bash
python retro-refiner.py -s /path/to/roms --commit
```

## Architecture

### Single-file design
Everything lives in `retro-refiner.py` with no external dependencies. YAML parsing, progress bars, and all network handling are built-in. System definitions are externalized to `data/systems.json`. The file is organized into major sections separated by `# ===` comment banners:

1. **Console Output Styling** (~lines 93-305) - `Style`, `Console`, `ProgressBar`, `ScanProgressBar` classes, plus `load_title_mappings()`
2. **System Data Loading** (~lines 307-420) - `load_system_data()` reads `data/systems.json` and populates all system lookup dicts at module load
3. **YAML Parser & Shutdown** (~lines 420-788) - `parse_simple_yaml()`, graceful shutdown handling
4. **Network Source Support** (~lines 788-3420) - URL parsing, HTML link extraction, connection pooling (`ConnectionPool`), download tools (aria2c/curl/urllib), `DownloadUI` (curses-based download progress), batch downloading, network source scanning
5. **Configuration** (~lines 3420-3860) - Default config template, `load_config()`, `apply_config_to_args()`, transfer/playlist/gamelist functions
6. **Libretro DAT File Support** (~lines 3863-4655) - `RomInfo`/`DatRomEntry` dataclasses, T-En translation DAT support, DAT parsing (Logiqx XML + ClrMamePro formats), ROM verification, `parse_rom_filename()`, `normalize_title()`, `select_best_rom()`
7. **MAME Arcade Filtering** (~lines 4656-5440) - `MameGameInfo`/`TeknoParrotGameInfo` dataclasses, catver.ini parsing, category include/exclude sets, clone selection, `filter_mame_roms()`
8. **TeknoParrot Filtering** (~lines 5440-5640) - Version parsing, platform filtering, deduplication
9. **LaunchBox Data** (~lines 5642-5920) - Rating downloads, XML parsing with `XMLPullParser` for progress tracking, top-N filtering
10. **Main Flow** (~lines 5920-end) - System detection helpers, `scan_for_systems()`, `filter_roms_from_files()`, `main()`

### Key data flow
1. `main()` parses args, loads config, validates sources
2. `scan_for_systems()` or `scan_network_source_urls()` discovers ROM files per system
3. For each system: either `filter_roms_from_files()` (console ROMs), `filter_mame_roms()` (arcade), or `filter_teknoparrot_roms()` (TeknoParrot)
4. Console ROM filtering: `parse_rom_filename()` → `RomInfo` → group by `normalize_title()` → `select_best_rom()` per group → post-selection CRC/DAT enrichment (only selected ROMs)
5. `--limit` enforcement: after each system's selection, truncate if total exceeds the cap; skip remaining systems once limit is reached
6. Transfer: copy/move/symlink/hardlink based on `--commit` mode

### Key dataclasses
- `RomInfo` (line ~3840): Parsed ROM metadata (title, region, language, revision, flags like is_beta/is_proto/is_translation)
- `DatRomEntry` (line ~3868): DAT file entry (name, description, CRC32, region, size)
- `MameGameInfo` (line ~4844): MAME game with parent/clone relationships
- `TeknoParrotGameInfo` (line ~4861): TeknoParrot game with version/platform info

### System data (`data/systems.json`)
All system definitions (144 systems) live in `data/systems.json`. At module load, `load_system_data()` reads this file and populates module-level globals:
- `KNOWN_SYSTEMS` — list of all system codes
- `EXTENSION_TO_SYSTEM` — file extension → system code (91 extensions)
- `FOLDER_ALIASES` — folder name → system code (215 aliases)
- `LIBRETRO_DAT_SYSTEMS` — system → No-Intro DAT name (101 systems)
- `REDUMP_DAT_SYSTEMS` — system → Redump DAT name (25 systems)
- `TEN_DAT_SYSTEMS` — system → T-En DAT prefix (44 systems)
- `LAUNCHBOX_PLATFORM_MAP` — LaunchBox platform name → system code (67 platforms)
- `DAT_NAME_TO_SYSTEM` — reverse of DAT dicts (lowercase DAT name → system)
- `SYSTEM_TO_LAUNCHBOX` — reverse of LaunchBox map (system → first platform name)
- `SORTED_DAT_NAMES` — `DAT_NAME_TO_SYSTEM` items pre-sorted by key length (longest first), used by `detect_system_from_path()`
- `SORTED_ALIASES` — `FOLDER_ALIASES` items pre-sorted by key length (longest first), used by `detect_system_from_path()`

The generation script `tools/generate_systems_json.py` can regenerate the JSON from hardcoded dicts (kept as a maintenance tool).

### Other lookup tables (still in code)
- `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` (~line 4885/4904): Arcade category filtering

### Title normalization pipeline
`normalize_title()` lowercases, strips punctuation, converts Roman numerals to Arabic, then applies mappings from `data/title_mappings.json` (1,194 Japan→English mappings in 50 categories). This is how regional variants like "Rockman" and "Mega Man" get grouped together.

### Network download pipeline
Auto-detects best tool: aria2c > curl > Python urllib. `DownloadUI` provides a curses-based real-time progress display with per-file status, stall detection, and automatic retry (3 attempts). Auto-tuning adjusts parallelism based on median file size.

## Testing

Tests import from the hyphenated module name using `importlib`:
```python
_spec = importlib.util.spec_from_file_location("retro_refiner", Path(__file__).parent.parent / "retro-refiner.py")
```

Test files:
- `tests/test_selection.py` - 134 unit tests: ROM parsing, selection, filtering, config, playlists, transfers, systems.json validation
- `tests/test_bandwidth.py` - Benchmark tool for download performance tuning
- `tests/test_network_sources.py` - Functional tests for network source operations

Maintenance tools:
- `tools/generate_systems_json.py` - Regenerate `data/systems.json` from hardcoded dicts (migration tool)

## Common Modification Points

- **New system**: Add entry to `data/systems.json` with `name` and relevant fields (`extensions`, `folder_aliases`, `dat_name`, etc.)
- **New title mapping**: Add to `data/title_mappings.json` (lowercase, no punctuation, Arabic numerals)
- **New filter pattern**: Add to `RERELEASE_PATTERNS` or `COMPILATION_PATTERNS` (pre-compiled `re.compile()` lists at module level)
- **New MAME category**: Edit `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` sets

## Performance Patterns

### Pre-compiled regex
All regex patterns used in hot paths (`parse_rom_filename()`, `normalize_title()`) are pre-compiled at module level as `_RE_*` constants (e.g., `_RE_EXTENSION`, `_RE_BETA`, `_RE_REGION`). Pattern lists (`RERELEASE_PATTERNS`, `COMPILATION_PATTERNS`, `_HACK_PATTERNS`) are lists of compiled `re.compile()` objects. When adding new patterns, add them as `re.compile()` to the appropriate module-level list.

### CRC caching
`get_cached_crc()` wraps CRC calculation with a persistent JSON cache (`_crc_cache.json` in the dest directory). Cache entries are keyed by filepath and invalidated by mtime+size changes. The cache is loaded/saved in `filter_roms_from_files()` and cleaned by `--clean`.

### Deferred CRC calculation
CRC/DAT enrichment runs only on selected ROMs (post-selection pass in `filter_roms_from_files()`), not on all ROMs in the parsing loop. This reduces CRC I/O by ~3-5x since only 1 ROM per title group needs verification.

## Platform Notes

- Cross-platform: Windows, macOS, Linux
- All Unicode symbols must use `SYM_*` constants (defined at module top) — never hardcode Unicode in `Console` methods or print statements. Windows uses ASCII fallbacks.
- Windows enables ANSI escape codes via `ctypes` (line ~63)
- `DownloadUI` uses curses on Unix, falls back on Windows
- Windows cp1252 console cannot render Unicode symbols — always use `SYM_*` constants

## XML Parsing Caveat

`ET.iterparse()` only works with filename strings (`str(path)`), not file objects. For progress tracking during XML parsing, use `ET.XMLPullParser` with manual chunk reading and `parser.feed(chunk)`.
