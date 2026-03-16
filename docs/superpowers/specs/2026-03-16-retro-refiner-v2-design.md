# Retro-Refiner v2 — Architecture Redesign

**Date:** 2026-03-16
**Status:** Draft
**Scope:** Rewrite of retro-refiner as a GUI-first application with modular architecture

## Context

Retro-Refiner started as a single-file CLI script and grew to ~11K lines with a tkinter GUI bolted on top. The current architecture has several pain points:

- **Single 11K-line file** with all logic interleaved
- **GUI communicates via subprocess** — launches `retro-refiner.py` as a child process because in-process threading caused GIL freezes with tkinter
- **Text output as the interface contract** — the GUI parses ANSI-colored stdout to display results
- **Duplicate configuration** — argparse for CLI, tkinter widgets for GUI, with manual bridging between them
- **No structured result data** — filtering results are printed as text and discarded; the GUI can't inspect or manipulate them

The rewrite keeps all proven core logic but restructures it into a proper GUI-first application.

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Approach | Rewrite in same repo | Logic is proven, just needs restructuring |
| Module structure | Full Python package (~10-15 files) | Clean separation of concerns |
| GUI-to-core communication | Direct function calls | Cleanest API, structured data |
| UI framework | pywebview (HTML/CSS/JS in native window) | Modern styling, zero Chrome dependency, lightweight |
| Layout | Sidebar + output panel | Settings always visible alongside output, no tab switching |
| Output during run | Live cards that build in real-time | Structured from the start, raw log as secondary view |
| Output after run | System cards with stats, bars, filter tags, expandable ROM lists | Replaces raw text with actionable UI |
| Theming | Dark + Light with accent color pickers | OS preference detection, personalization |
| CLI mode | Headless via `--run config.yaml` | Same core APIs, text output, GUI config format is the config |
| Manual selection | ROM picker table layered on filtered results | Per-system from cards, or global "Review All" view |

## Architecture

### Package Structure

```
retro_refiner/
    __init__.py          # Version, package metadata
    __main__.py          # Entry point: GUI by default, --run for headless

    # Core logic modules
    scanner.py           # Local + network source scanning, URL discovery
    filter.py            # ROM parsing, grouping, selection (console systems)
    mame.py              # MAME-specific: DAT parsing, category filtering, clone selection
    teknoparrot.py       # TeknoParrot: filename parsing, version dedup, platform filtering
    downloader.py        # DownloadUI, aria2c/curl/urllib, adaptive auto-tune, resume
    dat.py               # DAT file loading, CRC verification, title normalization
    ratings.py           # IGDB + LaunchBox rating data
    transfer.py          # Copy/move/symlink/hardlink, playlist generation
    config.py            # YAML config load/save, defaults, validation
    systems.py           # System data loading from systems.json
    network.py           # URL parsing, HTML scraping, connection pooling, scan caching

    # UI layer
    ui/
        app.py           # pywebview window setup, Python API exposed to JS
        api.py           # API class: methods callable from JavaScript
        assets/          # HTML, CSS, JS files for the web UI
            index.html
            app.css
            app.js
            components/  # Sidebar, cards, picker, log viewer

    # CLI layer
    cli.py               # Headless runner: loads config, calls core APIs, prints text
```

### Core API Design

Filter functions return structured result objects instead of printing text:

```python
@dataclass
class FilterResult:
    system: str
    selected: List[RomInfo]       # ROMs that passed all filters
    excluded: List[ExcludedRom]   # ROMs excluded, with reasons
    stats: FilterStats            # Counts, sizes, timing

@dataclass
class ExcludedRom:
    rom: RomInfo
    reason: str                   # "non-English (Japan)", "Medal Game", etc.

@dataclass
class FilterStats:
    source_count: int
    selected_count: int
    excluded_count: int
    source_size: int
    selected_size: int
    dat_matched: int
    filter_breakdown: Dict[str, int]  # reason -> count
```

Progress is reported via callbacks, not print statements:

```python
def scan_network_source(url, options, on_progress=None) -> ScanResult:
    """Scan a network source for ROM URLs.

    on_progress receives ProgressEvent objects:
      - ProgressEvent(phase="fetching", message="Fetching directory listing...")
      - ProgressEvent(phase="scanning", current=50, total=680, message="Scanning game folders")
      - ProgressEvent(phase="complete", message="Found 1032 URLs")
    """
```

The GUI's `api.py` wires these callbacks to JavaScript:

```python
class Api:
    def run_preview(self, config_dict):
        """Called from JS. Runs preview and pushes events to the UI."""
        config = Config.from_dict(config_dict)
        for system, urls in scan_results.items():
            result = filter_system(system, urls, config,
                                   on_progress=lambda e: self.push_event(e))
            self.push_event(SystemCompleteEvent(result))
```

JavaScript receives events and updates cards in real-time.

### GUI Layout

```
┌─────────────────┬──────────────────────────────────────┐
│ [Preview] [Run] │ Status bar          [Log] [Results]  │
│ [Stop]          │──────────────────────────────────────│
│─────────────────│                                      │
│ ▾ SOURCES       │  Results view:                       │
│   source list   │  ┌──────────────────────────────┐   │
│   + Folder +URL │  │ Summary banner               │   │
│   Destination   │  └──────────────────────────────┘   │
│─────────────────│  ┌──────────────────────────────┐   │
│ ▾ SELECTION     │  │ DREAMCAST card       216 GB  │   │
│   checkboxes    │  │ stats · bar · filters        │   │
│   region order  │  │ [View ROMs] [Review & Edit]  │   │
│─────────────────│  └──────────────────────────────┘   │
│ ▸ BUDGET/LIMITS │  ┌──────────────────────────────┐   │
│ ▸ NETWORK       │  │ MAME card            973 GB  │   │
│ ▸ OUTPUT OPTIONS│  │ stats · bar · filters        │   │
│ ▸ ADVANCED      │  │ [View ROMs] [Review & Edit]  │   │
│                 │  └──────────────────────────────┘   │
│                 │                                      │
│                 │ [Clear] [Copy] [Export]  ☑ Scroll    │
└─────────────────┴──────────────────────────────────────┘
```

**During a run:** Cards appear and update live as each system is processed. Progress bars fill, counts increment, filter tags appear. No raw text — everything is structured.

**After a run:** Cards show final stats. [Log] tab reveals the raw text output for debugging. [Results] tab (default) shows the cards.

**Review & Edit:** Opens the ROM picker for that system (see below).

### ROM Picker (Manual Selection)

A spreadsheet-like table for reviewing and hand-picking ROMs. Accessed from:
- **Per-system:** "Review & Edit" button on a system card
- **Global:** "Review All" button on the summary banner

Columns (sortable):
- Checkbox (selected/deselected)
- ROM name
- System (in global view)
- Region
- Size
- Rating score (when available)
- Status (selected / excluded + reason)

Features:
- Sort by any column
- Filter/search text box
- Bulk select/deselect
- "Show excluded" toggle — reveals filtered-out ROMs so users can override
- Changes persist — modified selections feed back into the transfer step

The picker layers on top of automated filtering. The flow is:
1. Automated filters run → produce selected + excluded lists
2. User opens picker → sees the result, can add/remove ROMs
3. User confirms → final selection drives the transfer/download

### Theming

- **Dark theme** (default) + **Light theme** with OS preference detection
- Both themes have an **accent color picker** — user chooses their highlight color
- Theme stored in config YAML alongside all other settings
- CSS custom properties for all theme-able values:
  ```css
  :root {
      --bg-primary: #0a0a1a;
      --bg-secondary: #16213e;
      --accent: #e94560;
      --text-primary: #ccc;
      /* ... */
  }
  ```

### Headless / CLI Mode

```bash
# Run with a config file (exported from GUI or hand-written)
retro-refiner --run config.yaml

# Run with a config file and commit
retro-refiner --run config.yaml --commit

# Export default config
retro-refiner --export-config > my-config.yaml
```

The config YAML is the same format the GUI saves/loads. No argparse duplication — the CLI reads the config and calls the same core APIs.

Text output in headless mode uses the same `FilterResult` objects, rendered as formatted text instead of HTML cards.

### Configuration Format

Single YAML format used by both GUI and CLI:

```yaml
sources:
  - "https://myrient.erista.me/files/Redump/Sega - Dreamcast/"
  - "https://myrient.erista.me/files/MAME/CHDs (merged)/"
destination: "C:/Users/atkin/Downloads/roms"

selection:
  english_only: true
  exclude_protos: false
  region_priority: [USA, World, Europe, Australia, Japan]

budget:
  top: null
  size_limit: null

network:
  auto_tune: true
  scan_workers: 16
  resume_downloads: false

output:
  transfer_mode: move
  flat: false
  playlists: false

theme:
  mode: dark  # dark | light | system
  accent: "#e94560"
```

### Migration Path

The rewrite lives in the same repo. Approach:

1. Create `retro_refiner/` package alongside existing files
2. Extract and refactor modules one at a time from `retro-refiner.py`
3. Build the pywebview UI against the new module APIs
4. Tests migrate to pytest (or stay with current framework, calling new APIs)
5. Once feature-complete, remove old `retro-refiner.py`, `retro-refiner-gui.py`, `retro-refiner-app.py`
6. Update PyInstaller spec for new entry point

### Dependencies

**New:**
- `pywebview` — native window with embedded WebView

**Unchanged:**
- Python 3.8+ stdlib (no other runtime deps)
- `aria2c` / `curl` (optional, auto-detected at runtime)
- PyInstaller (build-time only)

### Out of Scope

- Web server / remote access (this is a desktop app)
- Plugin system
- Multi-language UI
- Database backend (JSON/YAML files are sufficient)
