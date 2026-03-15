# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Retro-Refiner is a zero-dependency Python script (~10,900 lines in a single file `retro-refiner.py`) that filters ROM collections to select the best English version of each game. It supports 144 systems, local and network sources, and multiple arcade formats (MAME, FBNeo, TeknoParrot).

## Commands

### Run tests
```bash
python tests/test_selection.py
```
Note: `pytest` is not installed. Tests use `unittest` and are run directly.

### Lint
```bash
python -m pylint retro-refiner.py
python -m pylint retro-refiner-gui.py
```
CI runs pylint across Python 3.8/3.9/3.10 (see `.github/workflows/pylint.yml`). The `.pylintrc` disables complexity checks since this is a large single-file script by design. Current score: **10.00/10** on both files — avoid introducing new warnings.

### GUI
```bash
python retro-refiner-gui.py
```

### Dry run (preview only)
```bash
python retro-refiner.py -s /path/to/roms
```

### Commit mode (actually transfer files)
```bash
python retro-refiner.py -s /path/to/roms --commit
```

### With logging
```bash
python retro-refiner.py -s /path/to/roms --log-dir ./logs
```

## Architecture

### GUI (`retro-refiner-gui.py`)
Tkinter-based GUI wrapper that provides a tabbed settings interface for all ~60 CLI arguments. Zero external dependencies (tkinter is stdlib). Key design:
- **Import:** Uses the same `importlib` pattern as tests to import `retro-refiner.py` as a module
- **Output capture:** Redirects `sys.stdout`/`sys.stderr` to a `QueueWriter` that feeds a `queue.Queue`. GUI polls every 50ms via `root.after()`. `\r` carriage returns trigger line replacement for progress bars
- **Threading:** `main()` runs in a daemon thread. Cancel sets `_module._shutdown_requested = True` (GIL-atomic). Catches `SystemExit` from `main()`'s `sys.exit()` paths
- **ANSI color output:** ANSI escape codes from the base script are parsed into tkinter text tags (`_parse_ansi_text()`, `_insert_ansi_text()`). `Style.apply_theme()` is re-applied after import to ensure colors are on regardless of `isatty()`. Color mappings in `_ANSI_COLORS_DARK`/`_ANSI_COLORS_LIGHT` refresh on theme toggle via `_configure_ansi_tags()`
- **Layout:** 4 tabs (Setup, Selection, Output, Advanced) + bottom panel (output text, command preview + Copy, action buttons). Advanced tab uses two-column layout (Network+Options+Logging | Auth+TeknoParrot+Maintenance). PanedWindow sash dynamically positioned via `_position_sash()` to fit tab content. Progress bar hidden when idle, shown only during runs
- **Theming:** Light/dark theme with OS detection (Windows registry, macOS `defaults`, Linux `gsettings`). Toggle button shows current state ("Theme: Dark"/"Theme: Light"). `DARK_THEME`/`LIGHT_THEME` dicts define all colors including accent button, sublabel, and ANSI color palettes; `_apply_theme()` updates output text, listboxes, preview entry, ANSI tags, and all ttk widget styles
- **State persistence:** GUI state auto-saved to `.retro-refiner-gui-state.yaml` on window close, restored on next launch. Manual Save/Load buttons export/import to user-chosen YAML files
- **Maintenance buttons:** Clean Cache & Data (`--clean`), Update DATs (`--update-dats`), Update Ratings (`--update-ratings`) in Advanced tab — run without requiring sources
- **No changes to `retro-refiner.py`** — the GUI is purely a wrapper

### Single-file design
Everything lives in `retro-refiner.py` with no external dependencies. YAML parsing, progress bars, and all network handling are built-in. System definitions are externalized to `data/systems.json`. The file is organized into major sections separated by `# ===` comment banners:

1. **Console Output Styling** (~lines 98-453) - `DEFAULT_THEME`, `Style`, `Console`, `ProgressBar`, `ScanProgressBar` classes, plus `load_title_mappings()`
2. **System Data Loading** (~lines 454-600) - `load_system_data()` reads `data/systems.json` and populates all system lookup dicts at module load
3. **YAML Parser, Shutdown & Logging** (~lines 600-1012) - `parse_simple_yaml()`, graceful shutdown handling, `TeeWriter`, `close_log()`
4. **Network Source Support** (~lines 1013-3855) - URL parsing, HTML link extraction, connection pooling (`ConnectionPool`), download tools (aria2c/curl/urllib), `DownloadUI` (curses-based download progress), batch downloading, network source scanning
5. **Configuration** (~lines 3856-4572) - Config template, `load_config()`, `apply_config_to_args()`, transfer/playlist/gamelist functions. Config files are NOT auto-generated
6. **Libretro DAT File Support** (~lines 4573-5955) - `RomInfo`/`DatRomEntry` dataclasses, T-En translation DAT support, DAT parsing (Logiqx XML + ClrMamePro formats), ROM verification, `parse_rom_filename()`, `normalize_title()`, `select_best_rom()`, `download_additional_dats()`, `load_all_system_dats()`
7. **MAME Arcade Filtering** (~lines 5956-6773) - `MameGameInfo`/`TeknoParrotGameInfo` dataclasses, catver.ini parsing, category include/exclude sets, clone selection, `filter_mame_roms()`
8. **TeknoParrot Filtering** (~lines 6774-6976) - Version parsing, platform filtering, deduplication
9. **IGDB Rating Data** (~lines 6977-7267) - IGDB API integration, OAuth token management, game rating queries, progress bar
10. **LaunchBox Data & Budget** (~lines 7268-8809) - Rating downloads, XML parsing with `XMLPullParser` for progress tracking, `apply_top_n_filter()`, `apply_size_budget()`
11. **Main Flow** (~lines 8810-end) - System detection helpers, `scan_for_systems()`, `filter_roms_from_files()`, `main()`

### Visual style system
All output routes through the `Console` class using semantic color attributes from `Style`. The `DEFAULT_THEME` dict (~line 101) maps 35 semantic roles (e.g., `'success'`, `'error'`, `'tag_select'`) to base ANSI color names. `Style.apply_theme()` resolves these to ANSI escape codes. Colors are disabled automatically for non-TTY output or when `NO_COLOR` env var is set.

**Key Console methods:**
- `banner()`, `header(text)`, `section(text)`, `subsection(text)` — structural output
- `success(text)`, `error(text)`, `warning(text)`, `info(text)`, `detail(text)` — status messages
- `system_stat(system, text)` — `SYSTEM: text` lines with colored system name
- `verbose(tag, text)` — `  [TAG] text` lines with tag-specific colors (SKIP, SELECT, FILTER, DAT, CONFIG, DETECT, MATCH, INCLUDE, EXCLUDE, CLONE, VERSION, DEDUP)
- `error_block(title, lines)` — bordered error blocks (writes to stderr)
- `table_header()`, `table_rule()`, `table_row()`, `table_total()` — formatted tables
- `status(label, value)` — label:value pairs
- `blank()`, `text(text, indent)` — plain output

**Rules for adding output:**
- Never use raw `print()` for user-facing output — use a Console method
- `Console.error()` and `Console.error_block()` write to `sys.stderr`
- DownloadUI uses `Style.*` attributes directly (no duplicate color constants)
- Progress bars use `Style.PROGRESS_FILL`/`Style.PROGRESS_EMPTY` for colored bars
- The ~15 remaining raw `print()` calls are justified exceptions: signal handlers, inline `end=''` output, KeyboardInterrupt

### Key data flow
1. `main()` parses args, loads config (if `--config` specified or config file exists in source dir — no auto-generation), validates sources
2. `scan_for_systems()` discovers ROM files per system (auto-detects from both folder names and file extensions — no `--auto-detect` flag needed). For network sources, `scan_network_source_urls()` discovers ROM URLs
3. If `--dedupe-priority` is set without `--commit`, `run_dedupe_analysis()` runs a fast filename-only analysis and exits early. With `--dedupe-delete --commit`, it runs analysis then deletes duplicate files in-place from source directories (with confirmation prompt). With `--commit` alone (no `--dedupe-delete`), systems are reordered by priority (highest first), PC game lists are loaded as seed `claimed_titles`, and arcade systems are excluded from dedup
4. For each system: either `filter_roms_from_files()` (console ROMs), `filter_mame_roms()` (arcade), or `filter_teknoparrot_roms()` (TeknoParrot)
5. Console ROM filtering: `parse_rom_filename()` → `RomInfo` → group by `normalize_title()` → exclude `claimed_titles` (dedup) → `select_best_rom()` per group → post-selection CRC/DAT enrichment (only selected ROMs) → accumulate selected titles into `claimed_titles`
6. Budget enforcement (`--top`, `--limit`, `--size`): applied in both the network pre-filtering loop and the local processing loop. `remaining_size_budget` is initialized before the network loop and carries over to the local loop. `apply_size_budget()` uses greedy knapsack: sort by rating desc, then fill budget skipping items too large
7. Transfer: copy/move/symlink/hardlink based on `--commit` mode

### Key dataclasses
- `RomInfo` (line ~4549): Parsed ROM metadata (title, region, language, revision, flags like is_beta/is_proto/is_translation)
- `DatRomEntry` (line ~4578): DAT file entry (name, description, CRC32, region, size)
- `MameGameInfo` (line ~6144): MAME game with parent/clone relationships
- `TeknoParrotGameInfo` (line ~6161): TeknoParrot game with version/platform info

### System data (`data/systems.json`)
All system definitions (144 systems) live in `data/systems.json`. At module load, `load_system_data()` reads this file and populates module-level globals:
- `KNOWN_SYSTEMS` — list of all system codes
- `EXTENSION_TO_SYSTEM` — file extension → system code (91 extensions)
- `FOLDER_ALIASES` — folder name → system code (215 aliases)
- `LIBRETRO_DAT_SYSTEMS` — system → No-Intro/Redump DAT name (114 systems)
- `ADDITIONAL_DAT_SYSTEMS` — system → list of additional DAT names for digital/PSN variants (11 DATs across 7 systems)
- `REDUMP_DAT_SYSTEMS` — system → Redump DAT name (28 systems, all 22 available Redump DATs mapped)
- `TEN_DAT_SYSTEMS` — system → T-En DAT prefix (44 systems)
- `LAUNCHBOX_PLATFORM_MAP` — LaunchBox platform name → system code (67 platforms)
- `DAT_NAME_TO_SYSTEM` — reverse of DAT dicts (lowercase DAT name → system)
- `SYSTEM_TO_LAUNCHBOX` — reverse of LaunchBox map (system → first platform name)
- `SORTED_DAT_NAMES` — `DAT_NAME_TO_SYSTEM` items pre-sorted by key length (longest first), used by `detect_system_from_path()`
- `SORTED_ALIASES` — `FOLDER_ALIASES` items pre-sorted by key length (longest first), used by `detect_system_from_path()`

The generation script `tools/generate_systems_json.py` can regenerate the JSON from hardcoded dicts (kept as a maintenance tool).

### Other lookup tables (still in code)
- `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` (~line 6185/6204): Arcade category filtering

### Title normalization pipeline
`normalize_title()` lowercases, strips punctuation, converts Roman numerals to Arabic, then applies mappings from `data/title_mappings.json` (1,200+ mappings in 50+ categories). This is how regional variants like "Rockman" and "Mega Man" get grouped together.

### TOSEC naming support
`parse_rom_filename()` auto-detects TOSEC naming (first parenthesized token is a date). TOSEC-specific handling includes:
- **Dump flags:** `_RE_TOSEC_BAD_FLAGS` matches `[b]` (bad dump), `[o]` (overdump), `[a]` (alternate), `[cr ...]` (cracked with attribution) — all filtered
- **Multi-part:** `_RE_DISC` matches `(Part X of Y)`, `(Disk X of Y)`, and `(Disc N)` formats; `_collect_sibling_discs()` includes all parts when any part is selected
- **Version dedup:** Trailing version strings (`v1.0`, `v110`) are stripped from `base_title` and folded into the `revision` field so different versions group together
- **Revision suffix:** Trailing `rN` is stripped from titles and folded into revision
- **Bulk collections:** `COMPILATION_PATTERNS` filters numbered collection disks (Plato Courseware, Tigercub, BCS Disk, Modules Disk)
- **Cracked ROMs:** Detected by both `[cr]` flag and "Cracked" in title text → marked as pirate and filtered
- **Demo variants:** `(demo-playable)`, `(demo-slideshow)` etc. detected regardless of TOSEC date detection order

### Network download pipeline
Auto-detects best tool: aria2c > curl > Python urllib. `DownloadUI` provides a curses-based real-time progress display with per-file status, stall detection, and automatic retry (3 attempts). Auto-tuning adjusts parallelism based on median file size.

### DAT download priority
`get_libretro_dat_url()` returns URLs in priority order. For disc-based systems (in `REDUMP_DAT_SYSTEMS`), the Redump URL is tried **first** because the `dat/` folder on libretro-database often contains stub files instead of full DATs. For cartridge-based systems, No-Intro is tried first. `download_additional_dats()` downloads digital/PSN variant DATs (from `additional_dat_names` in systems.json) as `{system}_extra1.dat`, etc. `load_all_system_dats()` merges primary + additional DAT entries.

### Configuration
Config files are NOT auto-generated. `--config` explicitly loads a YAML/JSON config file. Without `--config`, existing configs are auto-discovered in the source directory (`retro-refiner.yaml`, `.yml`, `.json`). CLI args always override config values. GUI state persistence uses a separate mechanism (`.retro-refiner-gui-state.yaml`).

## Testing

Tests import from the hyphenated module name using `importlib`:
```python
_spec = importlib.util.spec_from_file_location("retro_refiner", Path(__file__).parent.parent / "retro-refiner.py")
```

Test files:
- `tests/test_selection.py` - 278 unit tests: ROM parsing, selection, filtering, config, playlists, transfers, size budget, english-only, multi-disc games, TOSEC naming, systems.json validation, IGDB integration, download throttle backoff, cross-platform dedup, standalone dedup analysis, version metadata
- `tests/test_bandwidth.py` - Benchmark tool for download performance tuning
- `tests/test_network_sources.py` - Functional tests for network source operations

Maintenance tools:
- `tools/generate_systems_json.py` - Regenerate `data/systems.json` from hardcoded dicts (migration tool)

## Common Modification Points

- **New CLI argument**: Add to `argparse` in `main()` AND add a corresponding widget in `retro-refiner-gui.py` (in the appropriate tab's `_create_*_tab()` method) AND add the arg mapping in `_build_argv()`
- **New system**: Add entry to `data/systems.json` with `name` and relevant fields (`extensions`, `folder_aliases`, `dat_name`, etc.)
- **New title mapping**: Add to `data/title_mappings.json` (lowercase, no punctuation, Arabic numerals)
- **New filter pattern**: Add to `RERELEASE_PATTERNS` or `COMPILATION_PATTERNS` (pre-compiled `re.compile()` lists at module level)
- **New MAME category**: Edit `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` sets
- **New Console output**: Use an existing `Console` method — never add raw `print()` for user-facing output
- **New verbose tag**: Add the tag name to the `tag_colors` dict in `Console.verbose()` and to `DEFAULT_THEME`
- **Theme change (CLI)**: Edit `DEFAULT_THEME` dict — maps semantic role names to `Style` base color attribute names
- **Theme change (GUI)**: Edit `DARK_THEME`/`LIGHT_THEME` dicts in `retro-refiner-gui.py` — `_apply_theme()` applies them to all widgets

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
- Colors respect `NO_COLOR` env var (https://no-color.org/) and non-TTY detection

### Logging
- **Run logs:** `--log-dir` enables timestamped run logs (`retro-refiner_YYYY-MM-DD_HHMMSS_mode.log`). `TeeWriter` mirrors all output to both the original stream and a log file with ANSI codes stripped. `close_log()` cleanly unwraps TeeWriter
- **Selection logs:** Written to `log_dir/{system}_selection_log.txt` when `--log-dir` is set. Generated during both preview and commit runs. Disabled by default (no longer written to dest dirs)
- **GUI logging:** "Log output to file" checkbox passes `--log-dir ./logs`. "Open Logs" button opens the directory in the system file explorer

### Maintenance commands
- **`--update-dats`:** Downloads No-Intro (76 cartridge) + Redump (28 disc) + additional digital/PSN DATs (11) + MAME arcade data + T-En translation DATs (44). Does NOT download ratings
- **`--update-ratings`:** Downloads IGDB + LaunchBox rating data independently. Requires IGDB credentials for IGDB data. Progress bar renders in both CLI and GUI
- **`--clean`:** Deletes cached downloads, DAT files, CRC caches, and generated data. Works without sources
- **`--yes`:** Skips confirmation prompts (dedupe-delete). GUI always passes this since it handles confirmation via its own dialogs

## Local Data Files (not in git)

- `data/AllPCGames.xml` — LaunchBox playlist XML containing the user's Windows game library. Used for local reference/testing. Excluded via `.gitignore`.

## XML Parsing Caveat

`ET.iterparse()` only works with filename strings (`str(path)`), not file objects. For progress tracking during XML parsing, use `ET.XMLPullParser` with manual chunk reading and `parser.feed(chunk)`.
