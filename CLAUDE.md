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
python tests/test_selection.py       # 300 core tests
python tests/test_v2_modules.py      # 60 module tests
python tests/test_v2_config.py       # 65 config tests
python tests/test_v2_systems.py      # 19 systems tests
python tests/test_v2_paths.py        # 3 path tests
python tests/test_v2_cli.py          # 36 CLI tests
python tests/test_v2_integration.py  # 5 integration tests
```
Note: `pytest` is not installed. Tests use a custom `TestResult` framework and are run directly.

### Lint
```bash
python -m pylint retro_refiner/
```
Current score: **10.00/10** — avoid introducing new warnings.

### Build executable
```bash
pip install pyinstaller pywebview
python -m PyInstaller --noconfirm retro-refiner.spec
```

## Architecture

### Package Structure
```
retro_refiner/
    __init__.py       # Version, key exports (Config, load_config, SystemData, etc.)
    __main__.py       # Entry point: GUI default, --run for headless
    paths.py          # get_base_path() / get_runtime_path() for PyInstaller compat
    systems.py        # SystemData dataclass, load_system_data() from data/systems.json
    config.py         # Config dataclass (nested), YAML parser, load/save, defaults
    network.py        # URL utils, HTML scraping, fetch, validation, scan cache, shutdown
    scanner.py        # ScanProgressBar, detect_system_from_path, scan_network_source_urls
    dat.py            # RomInfo, DatRomEntry, DAT parsing, CRC verification, title normalization
    filter.py         # parse_rom_filename, select_best_rom, filter_network_roms, 20+ regex patterns
    mame.py           # MameGameInfo, catver.ini parsing, category filtering, clone selection
    teknoparrot.py    # TeknoParrotGameInfo, version dedup, platform filtering
    downloader.py     # DownloadUI, Aria2cRPC, aria2c/curl/urllib, adaptive auto-tune
    transfer.py       # Copy/move/symlink/hardlink, playlist gen, gamelist gen
    ratings.py        # IGDB + LaunchBox rating data, combine/boost ratings
    dedup.py          # Cross-system dedup analysis, PC game list parsing
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
- **Layout:** Sidebar (280px, collapsible settings sections) + main output panel (live cards + log)
- **Communication:** JS calls Python via `window.pywebview.api.method_name()` (returns Promise)
- **Events:** Python pushes events to JS via `window.evaluate_js()` calling `handlePythonEvent()`
- **Threading:** Core operations run in daemon threads; events pushed to JS on completion
- **Theme:** Dark/light with CSS custom properties, accent color picker

### Config System
Single `Config` dataclass with nested sections (`SelectionConfig`, `NetworkConfig`, `OutputConfig`, etc.). Same YAML format for GUI save/load and CLI `--run`:
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
2. Sources validated (`network.validate_source`)
3. Network sources scanned (`scanner.scan_network_source_urls`) with scan caching (24h TTL)
4. Per-system filtering: `filter.filter_network_roms` (console), `mame.filter_mame_network_roms` (MAME), `teknoparrot.filter_teknoparrot_network_roms` (TeknoParrot)
5. Results returned as `FilterResult` dataclass → GUI renders as cards
6. Optional: ROM picker for manual review/edit
7. Transfer: copy/move/symlink/hardlink via `transfer.transfer_files`

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

### Shutdown Mechanism
`retro_refiner.network` provides thread-safe shutdown:
```python
from retro_refiner.network import request_shutdown, check_shutdown, reset_shutdown
```

## Key Dataclasses
- `RomInfo` (`dat.py`): Parsed ROM metadata (title, region, language, revision, flags)
- `DatRomEntry` (`dat.py`): DAT file entry (name, CRC32, region, size)
- `MameGameInfo` (`mame.py`): MAME game with parent/clone relationships, category, region
- `TeknoParrotGameInfo` (`teknoparrot.py`): TeknoParrot game with version/platform
- `SystemData` (`systems.py`): All system lookup dictionaries
- `Config` (`config.py`): Full app configuration with nested sections
- `FilterResult`, `ProgressEvent`, `ScanResult` (`models.py`): Structured API results

## Common Modification Points

- **New system**: Add entry to `data/systems.json`
- **New title mapping**: Add to `data/title_mappings.json` (lowercase, no punctuation, Arabic numerals)
- **New filter pattern**: Add `re.compile()` to `RERELEASE_PATTERNS` or `COMPILATION_PATTERNS` in `filter.py`
- **New MAME category**: Edit `MAME_INCLUDE_CATEGORIES` / `MAME_EXCLUDE_CATEGORIES` in `mame.py`
- **New config option**: Add field to appropriate `*Config` dataclass in `config.py`, add UI widget in `index.html`, wire in `api.py`
- **New GUI section**: Edit `retro_refiner/ui/assets/index.html` (single-file HTML/CSS/JS)
- **New API method**: Add to `retro_refiner/ui/api.py` (auto-exposed to JS)
- **Version string**: `__version__` in `retro_refiner/__init__.py`

## Performance Patterns

### Pre-compiled regex
All regex in hot paths (`parse_rom_filename`, `normalize_title`) are `_RE_*` module-level constants in `filter.py`. Pattern lists (`RERELEASE_PATTERNS`, `COMPILATION_PATTERNS`, `_HACK_PATTERNS`) are lists of compiled patterns.

### CRC caching
`get_cached_crc()` in `dat.py` uses persistent JSON cache (`_crc_cache.json`). Entries keyed by filepath, invalidated by mtime+size.

### Scan caching
Network scan results cached for 24h in `cache/_scan_cache.json`. Keyed by source URL. Cleaned by `--clean`. Respects `--no-cache`.

### Adaptive auto-tune
Download parallelism starts conservative for large files (parallel=4, conn=1) and ramps up by 1 every 60s of stability, backs off on errors.

## Testing

Tests use a custom `TestResult` framework (not pytest). Run directly: `python tests/test_file.py`

Test files:
- `tests/test_selection.py` — 300 tests: ROM parsing, selection, filtering, config, playlists, transfers, MAME, TeknoParrot, dedup, ratings
- `tests/test_v2_*.py` — 188 tests across 6 files covering all v2 modules

All tests import from `retro_refiner.*` package — no monolith imports.

## Platform Notes

- Cross-platform: Windows, macOS, Linux
- pywebview uses system WebView (Edge/WebKit) — no Chrome dependency
- `DownloadUI` in `downloader.py` uses curses on Unix, falls back on Windows
- Colors: `FORCE_COLOR=1` env var forces ANSI output; `NO_COLOR` disables
- Path helpers handle PyInstaller `sys._MEIPASS` for bundled builds

## Packaging & Versioning

### Version scheme
Date-based: `YYYY.MM.DD.HHMM`. `__version__ = "dev"` in `retro_refiner/__init__.py`. CI injects from git tag.

### Release workflow
```bash
git tag v2026.03.16.0945 && git push origin v2026.03.16.0945
```

### Dependencies
- **Runtime:** `pywebview` (only external dependency)
- **Optional:** `aria2c`, `curl` (auto-detected for downloads)
- **Build:** `pyinstaller`
