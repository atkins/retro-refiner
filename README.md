# Retro-Refiner

**A desktop app for building curated retro game collections.** Point it at ROM archives — local folders or web servers like Myrient — and it selects the best English version of each game across 144 systems. GUI-first, with a full CLI for automation.

## Quick Start

### Install
```bash
pip install pywebview
```

### Launch the GUI
```bash
python -m retro_refiner
```

### Or use the CLI
```bash
# Preview what would be selected from a Myrient archive (dry run)
python -m retro_refiner --run config.yaml

# GBA set with fan translations — one command
python -m retro_refiner --source "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy%20Advance/" --source "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20Advance%20%5BT-En%5D%20Collection/" --commit
```

Remove `--commit` to preview selections without downloading or copying anything.

---

## Features

- **One ROM per game** — groups regional variants and selects the best version (USA > World > Europe)
- **1,200+ title mappings** across 50 categories (Rockman = Mega Man, Pocket Monsters = Pokemon, etc.)
- **Fan translation support** — includes `[T-En]` translations for Japan-only games
- **Filter before download** — only selected ROMs are fetched from network sources
- **DAT verification** — validates against No-Intro/Redump checksums (CRC32)
- **Rating-based budgets** — keep only the top-rated games per system, or fit into a size limit
- **Arcade support** — MAME, FBNeo, and TeknoParrot with category filtering and version dedup
- **Cross-platform dedup** — remove duplicates across systems with priority ordering
- **144 systems** — Nintendo, Sega, Sony, Atari, NEC, SNK, arcade, computers, and more

## GUI

The primary interface is a pywebview desktop app with a sidebar for configuration and a results panel.

<!-- TODO: Add screenshot -->
<!-- See docs/mockup-results-cards.html for the design reference -->

- **Sidebar** — collapsible sections for sources, selection options, budget, network, and output settings
- **Live result cards** — each system gets a card showing selected/excluded counts, size, filter breakdown, and a progress bar
- **ROM picker** — expand any card to browse individual ROMs, see what was excluded and why
- **Scan caching** — network directory scans are cached so re-runs start instantly
- **Log and Results views** — toggle between raw log output and the card-based results view
- **Preview and Run modes** — dry-run preview or commit with one click

Launch with no arguments:
```bash
python -m retro_refiner
```

## CLI

The CLI supports all the same options. Use `--run` with a YAML config file or pass arguments directly.

### Config-based workflow
```bash
# Create a config, then run it
python -m retro_refiner --run my-collection.yaml --commit
```

### One-liner examples

```bash
# SNES with fan translations
python -m retro_refiner --source "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Super%20Nintendo%20Entertainment%20System/" --source "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Super%20Famicom%20%5BT-En%5D%20Collection/" --commit

# PlayStation (Redump + translations)
python -m retro_refiner --source "https://myrient.erista.me/files/Redump/Sony%20-%20PlayStation/" --source "https://myrient.erista.me/files/T-En%20Collection/Sony%20-%20PlayStation%20%5BT-En%5D%20Collection/" --commit

# MAME arcade
python -m retro_refiner --systems mame --commit

# TeknoParrot
python -m retro_refiner --source "https://myrient.erista.me/files/TeknoParrot/" --systems teknoparrot --commit

# Top 50 rated games per system, symlinked
python -m retro_refiner --source /path/to/roms --top 50 --link --commit
```

### Useful flags
```bash
python -m retro_refiner --list-systems          # Show all 144 supported systems
python -m retro_refiner --update-dats            # Re-download all DAT files
python -m retro_refiner --update-ratings         # Re-download IGDB + LaunchBox data
python -m retro_refiner --clean                  # Delete all cached data
```

For the full option reference, see the [CLI Reference wiki page](https://github.com/atkins/retro-refiner/wiki).

## Network Sources

Retro-Refiner can fetch ROMs directly from HTTP/HTTPS servers. All filtering happens before download — only selected ROMs are fetched.

- **Supported formats** — Apache/nginx autoindex, HTML link pages, FTP-style `<pre>` listings, table-based listings
- **Download tools** — auto-detects aria2c > curl > Python urllib
- **Parallel downloads** — configurable with `--parallel N` (default: 4)
- **Adaptive tuning** — adjusts parallelism based on median file size
- **Caching** — downloaded files cached locally; subsequent runs skip re-downloading
- **Multi-source merging** — combine official sets with translation collections in one command

### Archive.org

Archive.org requires authentication. Get credentials at https://archive.org/account/s3.php

```bash
export IA_ACCESS_KEY=your_access_key
export IA_SECRET_KEY=your_secret_key
python -m retro_refiner --source "https://archive.org/download/sega_saturn/" --parallel 4 --commit
```

## Arcade (MAME, FBNeo & TeknoParrot)

### MAME & FBNeo

Category-based filtering using `catver.ini` data (auto-downloaded on first run).

**Included:** Fighters, shooters, platformers, puzzles, sports, driving, light gun, maze, climbing games.
**Excluded:** Mahjong, casino, gambling, quiz, dance pad, mechanical, medal/redemption, BIOS/devices.

Clone selection picks the best regional version: USA > World > Europe > Asia > Japan.

```bash
python -m retro_refiner --systems mame                       # Latest MAME data
python -m retro_refiner --systems mame --mame-version 0.274  # Specific version
python -m retro_refiner --systems fbneo                      # FinalBurn Neo
```

### TeknoParrot

Modern arcade games with version deduplication and hardware platform filtering.

```bash
# Latest version of each game
python -m retro_refiner --source "https://myrient.erista.me/files/TeknoParrot/" --systems teknoparrot --commit

# Filter by hardware platform
python -m retro_refiner --source "https://myrient.erista.me/files/TeknoParrot/" --systems teknoparrot --tp-include-platforms "Sega Nu,Sega RingEdge" --commit
```

Supported platforms include Sega (Lindbergh, RingEdge, Nu, ALLS), Taito (Type X series, NESiCAxLive), Namco (System 246/256/357), and others.

## Filtering & Selection

### Included
- Official USA/Europe/World releases (latest revision preferred)
- Fan translations of Japan-only games (`[T-En]`)
- Untranslated Japan-only games when no English or translation exists
- Prototypes (excludable with `--exclude-protos`)

### Excluded
- Betas, demos, samples, promotional cartridges
- Re-releases (Virtual Console, Mini consoles, Anniversary Collections)
- BIOS files, pirate/unlicensed dumps, homebrew
- Multi-game compilations (X-in-1, Double Pack)
- Hacked ROMs (except pure translations)

### Translation priority
When combining official ROM sets with translation collections, official English releases are preferred over fan translations, which are preferred over untranslated foreign ROMs.

## Rating & Budget

Two rating sources are supported for `--top` and `--size` filtering:

- **Combined (default)** — merges IGDB + LaunchBox via vote-weighted averaging. Best coverage and reliability. Requires free IGDB credentials from https://dev.twitch.tv/console
- **LaunchBox** — no-auth fallback, used automatically when IGDB credentials are not set

```bash
# Top 50 rated per system
python -m retro_refiner --source /path/to/roms --top 50 --commit

# Fit best-rated games into 10 GB
python -m retro_refiner --source /path/to/roms --size 10G --commit

# Cap at 500 ROMs total
python -m retro_refiner --source /path/to/roms --limit 500 --commit
```

## 144 Supported Systems

Retro-Refiner supports 144 systems across all major platforms:

- **Nintendo** — NES, SNES, N64, GameCube, Wii, Switch, Game Boy/Color/Advance, DS, 3DS, Virtual Boy, Pokemon Mini
- **Sega** — SG-1000, Master System, Genesis, Sega CD, 32X, Saturn, Dreamcast, Game Gear, Pico
- **Sony** — PlayStation 1/2/3, PSP, PS Vita
- **Atari** — 2600, 5200, 7800, 800/XL/XE, ST, Jaguar, Lynx
- **NEC** — TurboGrafx-16, TurboGrafx-CD, PC-FX, SuperGrafx
- **SNK** — Neo Geo, Neo Geo CD, Neo Geo Pocket/Color
- **Arcade** — MAME, CPS1/2/3, Naomi, FBNeo, TeknoParrot
- **Computers** — C64, Amiga, ZX Spectrum, Amstrad CPC, MSX/MSX2, PC-88, PC-98, Sharp X68000, FM Towns, Apple II, TRS-80
- **Other** — ColecoVision, Intellivision, Vectrex, Odyssey 2, Channel F, 3DO, WonderSwan/Color, and more

Run `python -m retro_refiner --list-systems` for the full list with extensions and folder aliases.

## Configuration

YAML config files map to all CLI options. Config files are not auto-generated — create one manually or export from the GUI.

```yaml
# Sources
source:
  - "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy%20Advance/"
  - "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20Advance%20%5BT-En%5D%20Collection/"

# Selection
region_priority: "USA,World,Europe,Japan"
english_only: true
exclude_protos: false

# Filtering
include:
  - "*Mario*"
  - "*Zelda*"
exclude:
  - "*Demo*"

# Budget
top: 50
size: "10G"

# Output
link: true
playlists: true
gamelist: true

# Systems (omit for auto-detect)
systems:
  - nes
  - snes
  - gba
```

```bash
python -m retro_refiner --run config.yaml --commit
```

CLI arguments override config file settings.

## Requirements

- **Python 3.10+**
- **pywebview** — `pip install pywebview` (for the GUI)
- **Optional:** [aria2c](https://aria2.github.io/) for faster parallel downloads

## Documentation

Full guides, examples, and reference: **[Wiki](https://github.com/atkins/retro-refiner/wiki)**

Quick links: [Installation](https://github.com/atkins/retro-refiner/wiki/Installation) | [Examples](https://github.com/atkins/retro-refiner/wiki/Examples) | [Network Sources](https://github.com/atkins/retro-refiner/wiki/Network-Sources) | [Troubleshooting](https://github.com/atkins/retro-refiner/wiki/Troubleshooting)

## Disclaimer

**Retro-Refiner is a file management utility only.** It does not download, host, distribute, or provide access to any copyrighted content, ROMs, games, or proprietary software.

This tool:
- Does **not** include any games, ROMs, BIOS files, or copyrighted material
- Does **not** circumvent copy protection or DRM
- Does **not** facilitate piracy or copyright infringement
- Is functionally equivalent to file managers, search tools, or scripts that organize files by name

Retro-Refiner reads filenames and organizes files that already exist on the user's system or network. It performs the same operations as standard file management commands (`cp`, `mv`, `ln`) based on filename pattern matching.

**Users are solely responsible for** ensuring they have legal rights to any files they process, compliance with all applicable laws in their jurisdiction, and how they choose to use this tool.

The authors and contributors make no representations about the legality of any particular use case. This software is provided for legitimate purposes such as organizing personal backup collections.

## License

MIT License

Copyright (c) 2025 Atkins Meyer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
