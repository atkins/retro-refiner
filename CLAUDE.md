# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Retro-Refiner is a zero-dependency Python script (~9,000 lines in a single file `retro-refiner.py`) that filters ROM collections to select the best English version of each game. It supports 144 systems, local and network sources, and multiple arcade formats (MAME, FBNeo, TeknoParrot).

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
Everything lives in `retro-refiner.py` with no external dependencies. YAML parsing, progress bars, and all network handling are built-in. The file is organized into major sections separated by `# ===` comment banners:

1. **Console Output Styling** (~lines 93-665) - `Style`, `Console`, `ProgressBar`, `ScanProgressBar` classes, plus `load_title_mappings()`, YAML parser, and graceful shutdown handling
2. **Network Source Support** (~lines 665-3300) - URL parsing, HTML link extraction, connection pooling (`ConnectionPool`), download tools (aria2c/curl/urllib), `DownloadUI` (curses-based download progress), batch downloading, network source scanning
3. **Configuration** (~lines 3300-3740) - Default config template, `load_config()`, `apply_config_to_args()`, transfer/playlist/gamelist functions
4. **Libretro DAT File Support** (~lines 3741-4843) - `RomInfo`/`DatRomEntry` dataclasses, system-to-DAT mappings (`LIBRETRO_DAT_SYSTEMS`, `REDUMP_DAT_SYSTEMS`), T-En translation DAT support, DAT parsing (Logiqx XML + ClrMamePro formats), ROM verification, `parse_rom_filename()`, `normalize_title()`, `select_best_rom()`
5. **MAME Arcade Filtering** (~lines 4843-5627) - `MameGameInfo`/`TeknoParrotGameInfo` dataclasses, catver.ini parsing, category include/exclude sets, clone selection, `filter_mame_roms()`
6. **TeknoParrot Filtering** (~lines 5627-5830) - Version parsing, platform filtering, deduplication
7. **LaunchBox Data** (~lines 5830-6100) - Rating downloads, XML parsing with `XMLPullParser` for progress tracking, top-N filtering
8. **Main Flow** (~lines 6100-end) - System detection (`EXTENSION_TO_SYSTEM`, `FOLDER_ALIASES`), `scan_for_systems()`, `filter_roms_from_files()`, `main()`

### Key data flow
1. `main()` parses args, loads config, validates sources
2. `scan_for_systems()` or `scan_network_source_urls()` discovers ROM files per system
3. For each system: either `filter_roms_from_files()` (console ROMs), `filter_mame_roms()` (arcade), or `filter_teknoparrot_roms()` (TeknoParrot)
4. Console ROM filtering: `parse_rom_filename()` → `RomInfo` → group by `normalize_title()` → `select_best_rom()` per group
5. Transfer: copy/move/symlink/hardlink based on `--commit` mode

### Key dataclasses
- `RomInfo` (line ~3718): Parsed ROM metadata (title, region, language, revision, flags like is_beta/is_proto/is_translation)
- `DatRomEntry` (line ~3746): DAT file entry (name, description, CRC32, region, size)
- `MameGameInfo` (line ~5032): MAME game with parent/clone relationships
- `TeknoParrotGameInfo` (line ~5049): TeknoParrot game with version/platform info

### Important lookup tables (module-level dicts)
- `FOLDER_ALIASES` (~line 6927): 200+ folder name → system name mappings
- `EXTENSION_TO_SYSTEM` (~line 6774): File extension → system name mappings
- `LIBRETRO_DAT_SYSTEMS` (~line 3759): System → No-Intro DAT name
- `REDUMP_DAT_SYSTEMS` (~line 3879): System → Redump DAT name
- `TEN_DAT_SYSTEMS` (~line 4010): System → T-En DAT prefix
- `LAUNCHBOX_PLATFORMS` (~line 3920): LaunchBox platform → system name
- `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` (~line 5072/5091): Arcade category filtering

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
- `tests/test_selection.py` - Unit tests for ROM parsing, selection, filtering, config, playlists, transfers
- `tests/test_bandwidth.py` - Benchmark tool for download performance tuning
- `tests/test_network_sources.py` - Functional tests for network source operations

## Common Modification Points

- **New system**: Add to `FOLDER_ALIASES`, `EXTENSION_TO_SYSTEM`, and `LIBRETRO_DAT_SYSTEMS`/`REDUMP_DAT_SYSTEMS`
- **New title mapping**: Add to `data/title_mappings.json` (lowercase, no punctuation, Arabic numerals)
- **New filter pattern**: Add to `rerelease_patterns` or `compilation_patterns` in `parse_rom_filename()`
- **New MAME category**: Edit `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` sets

## Platform Notes

- Cross-platform: Windows, macOS, Linux
- All Unicode symbols must use `SYM_*` constants (defined at module top) — never hardcode Unicode in `Console` methods or print statements. Windows uses ASCII fallbacks.
- Windows enables ANSI escape codes via `ctypes` (line ~63)
- `DownloadUI` uses curses on Unix, falls back on Windows
- Windows cp1252 console cannot render Unicode symbols — always use `SYM_*` constants

## XML Parsing Caveat

`ET.iterparse()` only works with filename strings (`str(path)`), not file objects. For progress tracking during XML parsing, use `ET.XMLPullParser` with manual chunk reading and `parser.feed(chunk)`.
