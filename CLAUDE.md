# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Retro-Refiner is a GUI-first Python application that filters ROM collections to select the best English version of each game. It supports 144 systems, local and network sources, and multiple arcade formats (MAME, FBNeo, TeknoParrot). The GUI uses pywebview (HTML/CSS/JS in a native window).

## Commands

### Run the app (GUI)
```bash
python -m retro_refiner
```

### Run headless (CLI)
```bash
python -m retro_refiner --run config.yaml
python -m retro_refiner --run config.yaml --commit
python -m retro_refiner --export-config
```

### Run tests
```bash
python tests/test_selection.py       # 316 core tests
python tests/test_v2_modules.py      # 80 module tests
python tests/test_v2_config.py       # 65 config tests
python tests/test_v2_systems.py      # 19 systems tests
python tests/test_v2_paths.py        # 3 path tests
python tests/test_v2_cli.py          # 36 CLI tests
python tests/test_network.py         # 213 network tests
python tests/test_scanner_dat_transfer.py  # 138 scanner/DAT/transfer tests
python tests/test_api.py             # 176 API tests
```
Note: `pytest` is not installed. Tests use a custom `TestResult` framework and are run directly. **1,046 tests total, all passing.**

### Lint
```bash
python -m pylint retro_refiner/
```
Current score: **10.00/10** — avoid introducing new warnings.

### Title Mapping Analyzer
```bash
python tools/analyze_title_mappings.py          # use cached DATs
python tools/analyze_title_mappings.py --fresh   # force re-download
python tools/analyze_title_mappings.py --dry-run # report without modifying
```
Standalone tool that downloads DATs for all systems, detects missing title mappings via fuzzy matching, validates existing mappings, and writes results. Auto-adds high-confidence mappings (>= 0.93 fuzzy with safety filters), writes candidates to `tools/mapping_review.txt` for review. Categories in `title_mappings.json`: `regional_*` (auto-generated), `translations_*` and franchise names (manual).

### Build executable
```bash
pip install pyinstaller pywebview
python -m PyInstaller --noconfirm retro-refiner.spec
```

## Architecture

### Project Structure
```
tools/
    analyze_title_mappings.py  # Title mapping analyzer (standalone)
    mapping_review.txt         # Review candidates from last analyzer run
docs/plans/                    # Design docs and implementation plans
retro_refiner/
    __init__.py       # Version, key exports (Config, load_config, SystemData, etc.)
    __main__.py       # Entry point: GUI default, --run for headless
    paths.py          # get_base_path() / get_runtime_path() for PyInstaller compat
    systems.py        # SystemData dataclass, load_system_data() from data/systems.json
    config.py         # Config dataclass (nested), YAML parser, load/save, defaults
    network.py        # URL utils, HTML scraping, fetch, validation, scan cache, shutdown, SSRF checks
    scanner.py        # ScanProgressBar, detect_system_from_path, scan_network_source_urls
    dat.py            # RomInfo, DatRomEntry, DAT parsing, CRC verification, title normalization
    filter.py         # parse_rom_filename, select_best_rom, filter_network_roms, filter_roms_from_files
    mame.py           # MameGameInfo, catver.ini parsing, category filtering, clone selection
    teknoparrot.py    # TeknoParrotGameInfo, version dedup, platform filtering
    downloader.py     # DownloadUI, Aria2cRPC, aria2c/curl/urllib, adaptive auto-tune
    transfer.py       # Copy/move/symlink/hardlink/remove, dest validation, dest cleaning, playlist gen, gamelist gen
    ratings.py        # IGDB + LaunchBox rating data, combine/boost ratings
    dedup.py          # Cross-system dedup analysis, exclusion playlist parsing
    models.py         # Shared result types: FilterResult, ProgressEvent, ScanResult, etc.
    ui/
        app.py        # pywebview window launcher
        api.py        # Python API exposed to JavaScript (bridge class)
        assets/
            index.html  # Full web UI: sidebar layout, cards, ROM picker
    cli.py            # Headless runner: --run config.yaml
```

### GUI (pywebview)
- **Framework:** pywebview — HTML/CSS/JS rendered in system WebView (Edge on Windows, WebKit on macOS)
- **Layout:** Sidebar (280px) + main panel (Log, Results, Picker views)
- **Sidebar structure:** File Locations + Selection always visible; Dedup, Budget, Advanced behind "More Options" expander (Network/Output/Auth merged into Advanced)
- **Communication:** JS calls Python via `window.pywebview.api.method_name()` (returns Promise)
- **Events:** Python pushes events to JS via `window.evaluate_js()` calling `handlePythonEvent()`
- **Event routing:** `handlePythonEvent` → `LogRenderer.handle()` for structured log events, falls through to `_handleEventOriginal()` for status/card/log/progress/summary
- **Threading:** Core operations run in daemon threads; events pushed to JS on completion
- **Theme:** 10 themes (6 dark, 4 light) via `data-theme` attribute on `<html>`. CSS variables in `:root` / `[data-theme="name"]` blocks. Theme selector in bottom bar, persisted via `ThemeConfig.mode`.
- **Hotkeys:** F5 / Ctrl+R reloads the webview (saves config first)

### Config System
Single `Config` dataclass with nested sections (`SelectionConfig`, `NetworkConfig`, `OutputConfig`, `DeduplicationConfig`, `WindowConfig`, etc.). Same YAML format for GUI save/load and CLI `--run`. Note: `DeduperConfig` was renamed to `DeduplicationConfig` — field is `.deduplication` (not `.dedup`). `from_dict()` accepts legacy `dedup` key for backward compat.

- `source_settings: Dict[str, dict]` — per-source recursive scan settings keyed by path
- Auth credentials are **excluded** from state file persistence for security

`OutputConfig` fields:
```python
@dataclass
class OutputConfig:
    local_file_action: str = 'copy'    # copy/move/symlink/hardlink/remove
    flat: bool = False
    playlists: bool = False
    gamelist: Optional[str] = None      # EmulationStation gamelists dir
    retroarch_playlists: Optional[str] = None  # RetroArch .lpl playlists dir
    prefer_source: Optional[str] = None
    print_roms: bool = False
    validate_destination: bool = True   # Skip files already in dest
    clean_destination: bool = False     # Remove unselected files from dest
    crc_validation: bool = False        # CRC check during validation
```
Note: `transfer_mode` was renamed to `local_file_action` — `from_dict()` accepts the legacy key for backward compat.

```python
from retro_refiner.config import Config, load_config, save_config
config = Config()
config.selection.english_only = True
save_config(config, Path('config.yaml'))
```

### System Data
`SystemData` dataclass loaded from `data/systems.json` — no module globals. Access via:
```python
from retro_refiner.systems import load_system_data
data = load_system_data()
data.known_systems        # List[str], 144 systems
data.extension_to_system  # Dict[str, str], .nes → nes
data.folder_aliases       # Dict[str, str], megadrive → genesis
```

### Key Data Flow
1. Config loaded (from GUI state or YAML file)
2. Sources validated (`network.validate_source`) — includes SSRF checks for private IPs
3. Network sources scanned (`scanner.scan_network_source`) with scan caching (24h TTL)
4. Local sources scanned (`scanner.scan_local_sources`) with per-source recursive settings
5. System include/exclude filter applied (pill-based UI)
6. Per-system filtering: `filter.filter_network_roms` (console URLs), `filter.filter_roms_from_files` (local files), `mame.filter_mame_network_roms` (MAME), `teknoparrot.filter_teknoparrot_network_roms` (TeknoParrot)
7. Budget filters applied (--top, --limit, --size)
8. Cross-system dedup applied (if priority configured)
9. Results returned as structured events → GUI renders cards with preview titles
10. Optional: ROM picker for manual review/edit (changes auto-save with indicator)
11. Commit via `_commit_system()` in 4 phases: validate destination (skip existing, optional CRC check) → download remote files to dest (via `.rrdownload` temp files for crash safety) → transfer local files (copy/move/symlink/hardlink/remove) → clean destination (remove unselected files if enabled)

### `_do_run` Phases (api.py)
The main run method is split into extracted helper methods:
- `_validate_sources()` — source validation loop
- `_scan_sources()` — network + local scanning, returns (all_urls, all_sizes, local_systems, all_systems) or None
- `_filter_system()` — per-system filtering (network + local), returns (selected, excluded, size, source, source_size) tuple
- `_compute_fanfare()` — ROM content analysis and tidbit generation
- `_run_dedup()` — cross-system dedup pass
- `_apply_budget_filters()` — budget/limit/size constraints
- `_commit_system()` — per-system commit in 4 phases: (1) validate destination (skip files already present, optional CRC check), (2) download remote files directly to destination (uses `.rrdownload` temp files, renamed on completion for crash safety), (3) transfer local files via configured `local_file_action` (copy/move/symlink/hardlink/remove), (4) clean destination (remove unselected files if `clean_destination` enabled)
- `_compute_system_stats()` — per-system verbose stats (regions, years, sizes, formats, revisions, languages)
- `_write_run_logs()` — comprehensive log file output (4 file types) when log_dir configured
- `_download_with_aria2c()` — aria2c batch download with redirect pre-resolution, file-polling progress, and curl fallback
- `reset_and_restart()` — delete state/cache/DATs, relaunch app fresh
- `clean_data()` — delete scan cache, DAT files, CRC cache, state file, temp downloads

### Structured Log Events
Python emits structured events consumed by JS `LogRenderer`:

| Event Type | When | Rendered As |
|---|---|---|
| `system-start` | System begins filtering | Box-drawing header with system name + ROM count |
| `filter-tick` | Before filtering | Progress placeholder line |
| `system-complete` | System done | Breakdown with tree chars, expandable audit trail |
| `scan-summary` | Scanning done | Box with source/system/ROM totals |
| `fanfare` | Run complete | Box-drawing summary with ROM content tidbits |

### Structured Results
Filter functions return `FilterResult` (from `models.py`) instead of printing text:
```python
@dataclass
class FilterResult:
    system: str
    selected: list           # Selected ROM filenames/URLs
    excluded: List[ExcludedRom]  # Excluded with reasons
    stats: FilterStats       # Counts, sizes, breakdown
```

Progress via callbacks, not print:
```python
def scan_network_source(url, ..., on_progress=None) -> ScanResult:
    # on_progress receives ProgressEvent objects
```

### State Persistence
All UI state (config + window geometry) saved to `.retro-refiner-state.yaml` in `get_runtime_path()`. Auto-saved on window close via `window.events.closing` and periodically every 30s. Auto-restored on launch via `load_ui_state()` → `restoreUiState()`. Auth credentials are stripped before saving. `WindowConfig` dataclass holds x/y/width/height.

### Selection Modes
Three filtering modes controlled by `all_roms` and `best_version` config flags:
- `all_roms=True` → no filtering, all files passed through (UI: "Apply filters" unchecked)
- `all_roms=False` + `best_version=False` → individual filters only (patterns, year, english, protos) but no grouping
- `all_roms=False` + `best_version=True` → full 1G1R: group by title, select best per game

### ROM Picker
`get_system_roms()` returns all ROMs with region/status/reason populated from `parse_rom_filename()`. Manual selections stored in `_manual_selections` and `_picker_state` dicts on `Api`. Applied during commit via URL filtering. `reset_picker()` clears cached state. Picker state persists across reopens but clears on new scan. Picker refreshes in-place if a preview completes while the user is in the editor. Search covers filename, region, status, and reason fields.

### Cross-System Dedup
`_run_dedup()` in api.py walks systems in priority order (configured via ordered pills). Each system claims normalized titles; later systems have duplicates removed. Deduped ROMs show as "excluded" with reason "cross-platform duplicate" in the picker. Exclusion playlists (LaunchBox/RetroArch/XML) can seed the claimed-titles set.

### Filter Return Types
`filter_network_roms()` returns `FilterResult` dataclass. `filter_mame_network_roms()` and `filter_teknoparrot_network_roms()` return `(selected_urls, size_info_dict)` tuples — not `FilterResult`. A future refactor should unify these.

### Local File Filtering
Local files go through `filter_roms_from_files(dry_run=True)` with the same selection config as network sources. Results are combined with network filtering for accurate counts.

### Cancellation
`cancel_run()` sets `self._running = False` AND calls `network.request_shutdown()` to stop in-flight network operations. `_do_run()` calls `reset_shutdown()` at start.

### Shutdown Mechanism
`retro_refiner.network` provides thread-safe shutdown:
```python
from retro_refiner.network import request_shutdown, check_shutdown, reset_shutdown
```

### Clipboard
Platform-native clipboard APIs (no tkinter):
- Windows: PowerShell `Set-Clipboard` via UTF-8 temp file (cp1252 pipe can't handle box-drawing chars)
- macOS: `pbcopy` with UTF-8 encoding
- Linux: `xclip -selection clipboard` with UTF-8 encoding

### Display Names
Module-level `_SYSTEM_ABBREVS` frozenset and `_display_name(system)` helper in api.py convert system codes to human-readable names (e.g., `snes` → `SNES`, `game-boy-advance` → `Game Boy Advance`).

## Key Dataclasses
- `RomInfo` (`dat.py`): Parsed ROM metadata (title, region, language, revision, flags)
- `DatRomEntry` (`dat.py`): DAT file entry (name, CRC32, region, size)
- `MameGameInfo` (`mame.py`): MAME game with parent/clone relationships, category, region
- `TeknoParrotGameInfo` (`teknoparrot.py`): TeknoParrot game with version/platform
- `SystemData` (`systems.py`): All system lookup dictionaries
- `Config` (`config.py`): Full app configuration with nested sections
- `FilterResult`, `ProgressEvent`, `ScanResult` (`models.py`): Structured API results

## GUI Components

### Sidebar (index.html)
- **File Locations** (always visible): sources with drag-and-drop + per-source recursive toggle (works for both local and network sources), destination path picker with validate/CRC/clean options, local file action dropdown (hidden when all sources are URLs), multi-disc M3U + flatten toggles, system pills with All/None toggle
- **Selection** (always visible): "Apply filters" toggle with sub-options (1G1R, English, protos, betas, unlicensed, adult — adult hidden when no arcade systems), region priority, patterns, year range. All options use mobile-style toggle switches (hybrid layout: primary full-width, secondary in 2-column grid).
- **More Options** (collapsed): Deduplication (ordered priority pills, exclusion playlists), Budget & Limits, Advanced (network settings, DAT/CHD/cache toggles, scan depth, MAME version, ratings, EmulationStation/RetroArch/log directories, auth credentials)
- **Footer**: Save/Load/Reset buttons

### Path Pickers
Clickable path-picker UI component (folder icon, truncated path, tooltip, × clear). Used for destination, RetroArch playlists, log dir, DAT dir. `setPathPicker()` / `clearPathPicker()` / `browsePathPicker()` helpers.

### System Pills
Toggleable pill UI for system include/exclude and dedup priority ordering. `systemPillState` tracks enabled/disabled. `dedupPriorityOrder` tracks click-order for dedup priority with numbered prefixes.

### Result Cards
Per-system cards with stats, ratio bar, filter breakdown tags, preview titles (top 5 selected ROM names), and "Manage" button. `updateCardComplete()` clears prior content before repopulating (supports dedup updates in-place).

### Log Renderer (LogRenderer object)
Handles structured events (system-start, filter-tick, system-complete, scan-summary, fanfare). Verbose per-system stats: filter breakdown, region/format/year distribution, size histogram, largest/smallest ROM, revision counts. Scan summary box with source/system/ROM totals. Fanfare with throughput, space saved, system rankings, filter impact, notable finds, decade breakdown. Copy button (hidden on results/picker tabs) uses UTF-8 temp file on Windows for unicode support. Auto-switches to log tab on run start, results tab 1s after completion.

### Progress Indicators
Step indicators `[1/3] [2/3] [3/3]` (preview uses `[1/2] [2/2]`) with phase-specific stats:
- **Scanning**: folders/s, ETA
- **Filtering**: running totals (selected count, size), elapsed, ETA
- **Downloading**: aria2c batch with file-polling (files/s), elapsed, ETA; curl chunked; urllib per-file
- **Local transfers**: per-file progress via `transfer_files` callback

## Common Modification Points

- **New system**: Add entry to `data/systems.json`
- **New title mapping**: Add to `data/title_mappings.json` (lowercase, no punctuation, Arabic numerals). Or run `python tools/analyze_title_mappings.py` to auto-detect from DATs. Categories: `regional_*` (auto-generated), `translations_*` and franchise names (manual).
- **New filter pattern**: Add `re.compile()` to `RERELEASE_PATTERNS` or `COMPILATION_PATTERNS` in `filter.py`
- **New MAME category**: Edit `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` in `mame.py`
- **New config option**: (1) Add field to `*Config` dataclass in `config.py`, (2) add HTML element in `index.html`, (3) add to `gatherUiState()` JS function, (4) add to `update_config_from_ui()` in `api.py`, (5) add to `restoreUiState()` JS function. Example: `local_file_action` in `OutputConfig` controls how local files are transferred (copy/move/symlink/hardlink/remove).
- **New GUI section**: Edit `retro_refiner/ui/assets/index.html` (single-file HTML/CSS/JS)
- **New API method**: Add to `retro_refiner/ui/api.py` (instance methods auto-exposed to JS; static methods are NOT exposed)
- **Version string**: `__version__` in `retro_refiner/__init__.py`

## Performance Patterns

### Pre-compiled regex
All regex in hot paths (`parse_rom_filename`, `normalize_title`) are `_RE_*` module-level constants in `filter.py`. Pattern lists (`RERELEASE_PATTERNS`, `COMPILATION_PATTERNS`, `_HACK_PATTERNS`) are lists of compiled patterns.

### CRC caching
`get_cached_crc()` in `dat.py` uses persistent JSON cache (`_crc_cache.json`). Entries keyed by filepath, invalidated by mtime+size.

### Scan caching
Network scan results cached for 24h in `cache/_scan_cache.json`. Keyed by source URL. Cleaned by `--clean`. Respects `--no-cache`. Atomic writes via temp file + `os.replace()`.

### Adaptive auto-tune
Download parallelism starts conservative for large files (parallel=4, conn=1) and ramps up by 1 every 60s of stability, backs off on errors.

### Archive.org compatibility
Archive.org directory listings parse correctly via Pattern 2/3 in `parse_html_for_files_with_sizes`. Regex backtracking prevented by skipping Pattern 3 on pages without `<tr>` tags and capping scan to 200KB. Zip contents browsable via `/serve/{collection}/{system}.zip/` endpoint — individual ROM files inside zips have direct download URLs.

### Log file output
When `log_dir` is configured, writes 4 file types per run:
- `run_summary_{timestamp}.txt` — overall stats, per-system breakdown, filter impact
- `{system}_selected.txt` — every selected ROM with title/region/revision/source
- `{system}_excluded.txt` — every excluded network ROM with title/region
- `console_{timestamp}.txt` — complete console output (buffered from `_push_event('log')` calls)

## Testing

Tests use a custom `TestResult` framework (not pytest). Run directly: `python tests/test_file.py`

`TestResult` API: `results.ok(name)` and `results.fail(name, expected, actual)`. Global `results` instance (plural). No `assert_equal` or similar — write explicit `if`/`else` checks.

Test files:
- `tests/test_selection.py` — 316 tests: ROM parsing, selection, filtering, config, playlists, transfers, MAME, TeknoParrot, dedup, ratings
- `tests/test_v2_*.py` — 203 tests across 5 files covering all v2 modules
- `tests/test_network.py` — 213 tests: URL utils, size parsing, HTML parsing (all 5 patterns), SSRF validation, scan cache
- `tests/test_scanner_dat_transfer.py` — 138 tests: system detection, local scanning, DAT parsing (XML+ClrMamePro), title normalization, CRC, validate/clean destination, file transfers, playlist generation
- `tests/test_api.py` — 176 tests: display names, ETA/elapsed formatting, config management, clean_data, system stats, UI state, picker, clipboard, run state

All tests import from `retro_refiner.*` package — no monolith imports.

`tests/test_selection.py` uses `_filter_network_roms_compat()` wrapper that defaults `best_version=True` for backward compat. New `filter_roms_from_files` calls in tests that expect 1G1R must pass `best_version=True` explicitly.

## Security

- Auth credentials stripped from state file before saving to disk
- SSRF validation rejects private/localhost URLs in `validate_source()`
- Dynamic values in `innerHTML` escaped via `escapeHtml()` — `textContent`/`createElement` preferred
- Clipboard uses platform-native subprocesses, not tkinter
- `cancel_run()` propagates shutdown to network operations
- aria2c pre-resolves redirects via HEAD request to avoid encoded-character failures
- Config snapshot at run start for thread safety (`Config.from_dict(self._config.to_dict())`)
- `clean_data()` requires DAT file presence check before `rmtree`, plus user confirmation dialog
- Empty scan results not cached (prevents stale 0-URL cache from blocking future scans)

## Platform Notes

- Cross-platform: Windows, macOS, Linux
- pywebview uses system WebView (Edge/WebKit) — no Chrome dependency
- `DownloadUI` in `downloader.py` uses curses on Unix, falls back on Windows
- Colors: `FORCE_COLOR=1` env var forces ANSI output; `NO_COLOR` disables
- Path helpers handle PyInstaller `sys._MEIPASS` for bundled builds
- **Window icon**: `icon.ico` / `icon.png` in `ui/assets/`. Set at runtime via Windows ctypes (`LoadImageW` + `SendMessageW`) in `app.py:_set_window_icon()`. Referenced in `retro-refiner.spec` for PyInstaller builds.
- **CSS theming**: Never use hardcoded colors (#fff, #000, #1a1a2e) in CSS — use variables (`--text-heading`, `--text-on-accent`, `--bg-stripe`, `--border-subtle`). Light themes break otherwise.
- **Scrollbar**: Uses `var(--text-muted)` for hover color — no hardcoded values.
- **pywebview API**: Only instance methods are exposed to JS. `@staticmethod` methods are NOT visible on the bridge.

## Packaging & Versioning

### Version scheme
Date-based: `YYYY.MM.DD.HHMM`. `__version__ = "dev"` in `retro_refiner/__init__.py`. CI injects from git tag.

### Release workflow
```bash
git tag v2026.03.19.0100 && git push origin v2026.03.19.0100
```

### Dependencies
- **Runtime:** `pywebview` (only external dependency)
- **Optional:** `aria2c`, `curl` (auto-detected for downloads)
- **Build:** `pyinstaller`
