# Retro-Refiner

**Refine your RetroArch ROM collection down to the essentials.**

A portable Python script that simplifies the generation of RetroArch-friendly ROM sets. Point it at large ROM archives—local or network—and it automatically selects the best version of each game, based on your native language and filters out the clutter.

## TL;DR

Grab a refined ROM set from Myrient in one command:

```bash
# Game Boy Advance (No-Intro + English translations, best of each game)
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy%20Advance/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20Advance%20%5BT-En%5D%20Collection/" \
  --commit
```

That's it. The script combines both sources, picks the best English version of each game (official release or fan translation), and downloads only what you need.

<details>
<summary>More systems (click to expand)</summary>

**NES**
```bash
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Nintendo%20Entertainment%20System%20(Headered)/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Famicom%20%5BT-En%5D%20Collection/" \
  --commit
```

**SNES**
```bash
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Super%20Nintendo%20Entertainment%20System/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Super%20Famicom%20%5BT-En%5D%20Collection/" \
  --commit
```

**Game Boy**
```bash
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20%5BT-En%5D%20Collection/" \
  --commit
```

**Game Boy Color**
```bash
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy%20Color/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20Color%20%5BT-En%5D%20Collection/" \
  --commit
```

**Nintendo DS**
```bash
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Nintendo%20DS%20(Decrypted)/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Nintendo%20DS%20%5BT-En%5D%20Collection/" \
  --commit
```

**Sega Genesis / Mega Drive**
```bash
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Sega%20-%20Mega%20Drive%20-%20Genesis/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Sega%20-%20Mega%20Drive%20%5BT-En%5D%20Collection/" \
  --commit
```

**PlayStation**
```bash
python retro-refiner.py \
  -s "https://myrient.erista.me/files/Redump/Sony%20-%20PlayStation/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Sony%20-%20PlayStation%20%5BT-En%5D%20Collection/" \
  --commit
```

</details>

**Dry run first?** Remove `--commit` to preview what will be selected without downloading anything.

---

## Why Retro-Refiner?

Inspired by the [1G1R (One Game, One ROM)](https://unexpectedpanda.github.io/retool/retool-1g1r/) philosophy, Retro-Refiner automatically selects the single best version of each game—no duplicates, no clutter, just the ROMs you actually want to play.

There are many great ROM archive sites available, but they often contain every regional variant, beta, demo, and re-release ever dumped. Retro-Refiner makes it easy to grab optimized, customized sets from these archives:

- **Built for large archives**: Handles massive No-Intro and Redump collections with ease
- **Network source support**: Fetch ROMs directly from HTTP/HTTPS servers—no manual downloading required
- **RetroArch optimized**: Generates clean playlists (.lpl), proper folder structures, and gamelist.xml files
- **Flexible output**: Create sets for handhelds, mini consoles, full desktop setups, or anything in between
- **Filter before download**: When using network sources, only selected ROMs are downloaded—saving bandwidth and time

Whether you're building a curated collection for a Raspberry Pi, populating a MiSTer, or setting up a full RetroArch installation, Retro-Refiner helps you get exactly what you need.

## Features

### ROM Selection
- **One ROM per game**: Groups regional variants and selects the single best version of each game
- **Smart filtering**: Automatically excludes betas, demos, re-releases, compilations, BIOS, and pirate dumps
- **Language priority**: Prefers English releases (USA > World > Europe > Australia) - fully customizable
- **Translation support**: Includes fan translations `[T-En]` for Japan-only games
- **Japan-only inclusion**: Keeps untranslated Japan exclusives when no English version exists
- **1,194 title mappings**: Correctly groups regional variants (Rockman→Mega Man, Pocket Monsters→Pokemon, etc.) across 50 categories

### Network Downloads
- **Direct archive access**: Fetch ROMs directly from HTTP/HTTPS servers—no manual downloading
- **Filter before download**: Only selected ROMs are downloaded, saving bandwidth and time
- **Multi-source merging**: Combine official sets with translation collections in one command
- **Parallel downloads**: Configurable concurrent downloads with aria2c/curl support

### Verification & Accuracy
- **DAT verification**: Validates ROMs against No-Intro/Redump checksums (CRC32)
- **DAT-based selection**: Uses checksums to identify ROMs, not just filenames
- **Selection logs**: Detailed logs showing exactly what was selected and why

### Usability
- **Safe by default**: Dry run mode previews selections without transferring any files
- **Cross-platform**: Works on Windows, macOS, and Linux with no dependencies
- **Auto-detection**: Detects systems from folder names (200+ aliases) or file extensions (90+)
- **Progress bars**: Visual feedback with ETA, throughput, and per-file status
- **Graceful shutdown**: Ctrl+C stops cleanly between operations

## Documentation

📖 **[Full Documentation Wiki](https://github.com/atkins/retro-refiner/wiki)** — Detailed guides, examples, and reference

Quick links: [Installation](https://github.com/atkins/retro-refiner/wiki/Installation) · [Examples](https://github.com/atkins/retro-refiner/wiki/Examples) · [Network Sources](https://github.com/atkins/retro-refiner/wiki/Network-Sources) · [Troubleshooting](https://github.com/atkins/retro-refiner/wiki/Troubleshooting)

## Requirements

- Python 3.10+
- No external dependencies (YAML parsing and progress bars are built-in)

## Quick Start

### Basic Usage
```bash
# Preview what would be selected (dry run - no files touched)
python retro-refiner.py -s /path/to/roms

# Actually copy the refined set
python retro-refiner.py -s /path/to/roms --commit
```

### Download from Myrient
```bash
# GBA: No-Intro + fan translations, best English version of each game
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy%20Advance/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20Advance%20%5BT-En%5D%20Collection/" \
  --parallel 8 --commit
```

### Download from Archive.org
Archive.org requires authentication. Get your credentials at https://archive.org/account/s3.php

```bash
# Sega Saturn: Redump set, filtered to best English version of each game
# Set credentials via environment (safer, no keys in shell history)
export IA_ACCESS_KEY=your_access_key
export IA_SECRET_KEY=your_secret_key
python retro-refiner.py \
  -s "https://archive.org/download/sega_saturn/" \
  --parallel 4 --commit

# Or pass credentials directly
python retro-refiner.py \
  -s "https://archive.org/download/sega_saturn/" \
  --ia-access-key YOUR_KEY --ia-secret-key YOUR_SECRET \
  --parallel 4 --commit
```

### Space-Saving with Symlinks
```bash
# Keep your full archive, create a curated symlink set (~1MB vs copying GBs)
python retro-refiner.py -s /Games/archive -d /Games/refined --link --commit
```

### Build a Curated Collection
```bash
# Only Mario, Zelda, and Metroid games
python retro-refiner.py -s /path/to/roms \
  --include "*Mario*" --include "*Zelda*" --include "*Metroid*" --commit

# Retro-only (pre-2000) with playlists
python retro-refiner.py -s /path/to/roms --year-to 1999 --playlists --commit

# Japanese versions first (for collectors/language learners)
python retro-refiner.py -s /path/to/roms --region-priority "Japan,USA,Europe" --commit
```

### More Options
```bash
python retro-refiner.py --systems nes snes genesis gba  # Specific systems only
python retro-refiner.py --no-verify --no-dat            # Fast mode (skip verification)
python retro-refiner.py --list-systems                  # Show all 144 supported systems
```

Press `Ctrl+C` to gracefully stop at any time (press twice to force exit).

## Directory Structures

### Folder-based (Recommended)
ROMs organized in system subfolders:
```
roms/
├── nes/
│   ├── Contra (USA).zip
│   └── Super Mario Bros. (USA).zip
├── snes/
│   └── Chrono Trigger (USA).zip
└── genesis/
    └── Sonic the Hedgehog (USA).zip
```

Folder names are flexible - these all work:
- `nes`, `famicom`, `nintendo`
- `snes`, `super-nes`, `superfamicom`
- `genesis`, `megadrive`, `mega-drive`
- `n64`, `nintendo64`, `nintendo-64`

### Flat Directory (--auto-detect)
For ROMs in a single folder, use `--auto-detect` to identify systems by file extension:
```bash
python retro-refiner.py -s /path/to/mixed-roms --auto-detect
```

### Network Sources (HTTP/HTTPS)
ROMs can be fetched from web servers. The scanner handles a wide variety of page formats:
```bash
# Use network source
python retro-refiner.py -s https://myserver.com/roms/

# Mix local and network sources
python retro-refiner.py -s /local/roms -s https://myserver.com/roms/

# Specify custom cache directory
python retro-refiner.py -s https://myserver.com/roms/ --cache-dir /path/to/cache
```

**Supported Page Formats:**
- Apache/nginx autoindex directory listings
- Custom HTML pages with download links
- FTP-style text listings in `<pre>` blocks
- Table-based file listings
- Pages with various link formats (href, data-url, onclick)

**Features:**
- **Filter-before-download**: All filtering (patterns, regions, proto/beta exclusions) happens before downloading
- **Download summary**: Shows what will be downloaded before starting
- Only selected ROMs are downloaded, saving bandwidth and time
- Automatic redirect following
- Recursive subdirectory scanning (up to 3 levels deep)
- URL normalization (relative paths, `../`, encoded characters)
- Robust link extraction from various HTML structures
- Verification automatically disabled (files verified by filename only)

**Caching:**
- Downloaded files are cached locally in `<source>/cache/` by default
- Subsequent runs use cached files without re-downloading
- Use `--cache-dir` to specify a custom cache location
- Use `--clean` to delete cache and start fresh

**Download Performance:**
- Parallel downloads with `--parallel N` (default: 4)
- Auto-detects best download tool: aria2c > curl > Python urllib
- Install aria2c for best performance: `brew install aria2` (macOS) or `apt install aria2` (Linux)
- Live progress display showing active downloads with per-file progress and recent completions

## Arcade Filtering (MAME & FBNeo)

MAME and FBNeo ROMs use category-based filtering with shared `catver.ini` data.

### Setup
1. Place ROMs in `mame/` or `fbneo/` folder
2. Place CHD files in subfolders: `mame/gamename/game.chd`
3. Data files are **automatically downloaded** on first run

### Usage
```bash
# MAME
python retro-refiner.py --systems mame                       # Auto-download latest MAME data
python retro-refiner.py --systems mame --mame-version 0.274  # Use specific MAME version
python retro-refiner.py --systems mame --no-chd              # Skip CHD files

# FBNeo
python retro-refiner.py --systems fbneo                      # Uses FBNeo DAT

# Both together
python retro-refiner.py --systems mame fbneo

# Custom data directory
python retro-refiner.py --dat-dir /path/to/data
```

### Data Files
All DAT files are stored in `dat_files/` directory:

| File | Source | Purpose |
|------|--------|---------|
| `catver.ini` | Progetto Snaps | Game categories (shared) |
| `MAME 0.284 (arcade).dat` | Progetto Snaps | MAME game metadata |
| `FBNeo_Arcade.dat` | Progetto Snaps | FBNeo game metadata |
| `nes.dat`, `snes.dat`, etc. | libretro | Console ROM verification |

### MAME Selection Criteria

**Included:**
- Fighters, shooters, platformers, puzzles, sports
- Driving/racing games (playable with gamepad)
- Light gun games
- Ball & paddle, maze, climbing games
- Mature games (if playable)

**Excluded:**
- Mahjong, casino, gambling, slot machines
- Quiz games
- Dance pad games (DDR, etc.)
- Mechanical/electromechanical games
- Medal/redemption games
- BIOS and device files
- Non-arcade (computers, consoles, handhelds)

### Clone Selection
For games with multiple versions (clones), the best regional version is selected:
USA > World > Europe > Asia > Japan

## Selection Criteria

### Included
- Official USA/Europe/World releases (latest revision preferred)
- Fan translations of Japan-only games (marked with `[T-En]`)
- Untranslated Japan-only games when no English or translation exists
- Prototype versions (marked with `(Proto)`)

### Translation Preference (Multi-Source)
When combining official ROM sets with translation collections:
- Official English releases → preferred over fan translations
- Fan translations → preferred over untranslated foreign ROMs
- This ensures you get the best playable version of each game

### Excluded
- Beta versions
- Demo/Kiosk/Caravan/Taikenban versions
- Promotional cartridges
- Sample ROMs
- Re-releases (Virtual Console, Mini consoles, Anniversary Collections)
- BIOS files
- Pirate/Unlicensed dumps
- Homebrew
- Multi-game compilations (X-in-1, Double Pack, etc.)
- Hacked ROMs (except pure translations)

## Title Mappings

Retro-Refiner includes **1,194 mappings** across 50 categories for regional title differences and T-En translation matching:

### Major Series (28 categories, 347 mappings)

| Series | Mappings | Examples |
|--------|----------|----------|
| Pokemon | 69 | Pocket Monsters Aka → Pokemon Red |
| Mega Man | 50 | Rockman X → Mega Man X, EXE → Battle Network |
| Famicom Mini | 31 | Famicom Mini → Classic NES Series |
| Castlevania | 22 | Akumajou Dracula → Castlevania |
| Kirby | 16 | Hoshi no Kirby → Kirby's Dream Land |
| Zelda | 13 | Zelda no Densetsu → Legend of Zelda |
| Bomberman | 12 | Baku Bomberman → Bomberman 64 |
| Dragon Quest | 12 | Dragon Quest → Dragon Warrior |
| TMNT | 12 | Hero Turtles (EU) → Ninja Turtles |
| Fire Emblem | 10 | Japanese subtitles → English names |
| Donkey Kong | 9 | Super Donkey Kong → DK Country |
| Goemon | 9 | Ganbare Goemon → Mystical Ninja |
| Puyo Puyo | 9 | Regional variants and sequels |

### T-En Translation Mappings (22 categories, 847 mappings)

Automatically groups Japan ROMs with their fan translation counterparts when using both No-Intro and T-En sources:

| System | Mappings | Notable Titles |
|--------|----------|----------------|
| PlayStation | 93 | Persona 2, Policenauts, Moon, LSD |
| NES | 88 | Wizardry Gaiden, Metal Storm, Dragon Ball Z |
| SNES | 84 | Bahamut Lagoon, Live A Live, Star Ocean |
| Nintendo DS | 70 | Ni no Kuni, Soma Bringer, 7th Dragon |
| Saturn | 67 | Shining Force 3, Princess Crown, Sakura Wars |
| Game Boy Color | 60 | Star Ocean Blue Sphere, Medabots 3/4 |
| GBA | 58 | Mother 3, Rhythm Tengoku, Fire Emblem |
| Genesis | 58 | Phantasy Star series, Pulseman, Langrisser |
| TG-16/PC Engine | 53 | Ys IV, Snatcher, Tengai Makyou |
| Dreamcast | 42 | Shenmue, Napple Tale, Under Defeat |
| N64 | 36 | Animal Forest, Sin and Punishment, Custom Robo |
| Game Gear | 29 | Shining Force Final Conflict, Lunar |
| TG-CD | 19 | Castlevania Rondo of Blood, Ys IV |
| WonderSwan | 16 | Klonoa Moonlight Museum, Clock Tower |
| Master System | 10 | Phantasy Star, Fist of the North Star |

## Output

### Refined ROMs
```
<source>_refined/
├── nes/           (~2,000 ROMs)
├── snes/          (~2,300 ROMs)
├── genesis/       (~1,200 ROMs)
├── gba/           (~1,800 ROMs)
└── ...            (144 systems supported)
```

### Selection Logs
Each system folder contains `_selection_log.txt` with:
- Total ROMs scanned
- Unique games found
- ROMs selected
- List of selected ROMs with metadata
- List of skipped games

## Command Line Options

### Basic Options
| Option | Description |
|--------|-------------|
| `-s, --source` | Source ROM directory (can specify multiple times) |
| `-d, --dest` | Destination directory (default: `<source>_refined`) |
| `-y, --systems` | Systems to process (default: auto-detect) |
| `-a, --auto-detect` | Auto-detect systems from file extensions |
| `-c, --commit` | Actually transfer files (default is dry run: no copy/move/link/download) |
| `-v, --verbose` | Show detailed output (filtering decisions, selections) |
| `--config` | Path to config file (default: `retro-refiner.yaml`) |
| `--list-systems` | Show all supported systems |

### File Operations
| Option | Description |
|--------|-------------|
| `--link` | Create symbolic links instead of copying |
| `--hardlink` | Create hard links instead of copying |
| `--move` | Move files instead of copying |
| `--flat` | Output all ROMs to single folder (no subfolders) |

### Language Priority
| Option | Description |
|--------|-------------|
| `--region-priority` | Set language priority via region order (e.g., `"USA,Europe,Japan"` for English first) |
| `--keep-regions` | Keep multiple language versions (e.g., `"USA,Japan"` for English and Japanese) |

### Filtering
| Option | Description |
|--------|-------------|
| `--include` | Include only matching patterns (glob-style) |
| `--exclude` | Exclude matching patterns (glob-style) |
| `--exclude-protos` | Exclude prototype ROMs (included by default) |
| `--include-betas` | Include beta ROMs |
| `--include-unlicensed` | Include unlicensed ROMs |
| `--year-from` | Filter by year (minimum) |
| `--year-to` | Filter by year (maximum) |

### Export Options
| Option | Description |
|--------|-------------|
| `--playlists` | Generate M3U playlists |
| `--gamelist` | Generate EmulationStation gamelist.xml |
| `--retroarch-playlists` | Generate Retroarch .lpl playlists to directory |

### Multi-Source
| Option | Description |
|--------|-------------|
| `-s` (multiple) | Merge multiple source directories |
| `--prefer-source` | Prefer ROMs from this source for duplicates |

### Network Options
| Option | Description |
|--------|-------------|
| `--cache-dir` | Directory for caching network downloads |
| `-p, --parallel` | Number of parallel downloads (default: 4) |

### DAT Options
| Option | Description |
|--------|-------------|
| `--no-verify` | Skip ROM checksum verification |
| `--no-dat` | Use filename parsing instead of DAT metadata |
| `--dat-dir` | Directory for DAT files |
| `--mame-version` | MAME version for downloads |
| `--no-chd` | Skip CHD files for MAME |
| `--clean` | Delete cache, DAT files, and generated data |

### Default Behaviors
| Feature | Default | Override |
|---------|---------|----------|
| File operations | Dry run (analyzes but doesn't copy/move/link/download) | `--commit` |
| DAT verification | Enabled (disabled for network sources) | `--no-verify` |
| DAT metadata | Enabled | `--no-dat` |
| Transfer mode | Copy | `--link`, `--hardlink`, `--move` |

## Configuration File

On first run, Retro-Refiner automatically generates `retro-refiner.yaml` in your source directory with all options documented. You can then customize it as needed.

To use a custom config file location:
```bash
python retro-refiner.py --config /path/to/myconfig.yaml
```

Example configuration:

```yaml
# Region settings
region_priority: "Japan,USA,Europe"
keep_regions: "USA,Japan"

# Filtering
include:
  - "*Mario*"
  - "*Zelda*"
exclude:
  - "*Demo*"
exclude_protos: false  # protos included by default
include_betas: false
year_from: 1990
year_to: 1999

# Output
flat: false
link: true  # Use symlinks

# Systems
systems:
  - nes
  - snes
  - genesis

# Export
playlists: true
gamelist: true
```

CLI arguments override config file settings.

## ROM Verification & DAT Matching

By default, Retro-Refiner verifies ROMs against libretro No-Intro DAT files and uses DAT metadata for improved accuracy. DAT files are auto-downloaded on first run.

### Verification (enabled by default)
Checks ROM checksums (CRC32) against known good dumps:
- Generates `_verification_report.txt` in each system folder
- Shows verified (known good), unknown (not in DAT), and bad (unreadable) ROMs

### DAT Metadata (enabled by default)
Uses DAT files as the source for game names and regions:
- More accurate region detection
- Handles non-standard filenames
- Identifies games by checksum, not filename

### Disable for Faster Processing
```bash
# Skip verification only
python retro-refiner.py --no-verify

# Skip DAT metadata (use filename parsing)
python retro-refiner.py --no-dat

# Skip both (fastest, filename-only mode)
python retro-refiner.py --no-verify --no-dat
```

### Supported Systems for DAT
DAT files are auto-downloaded from [libretro-database](https://github.com/libretro/libretro-database) for 100+ systems including:
- Nintendo: NES, SNES, N64, GB, GBC, GBA, DS, Virtual Boy
- Sega: Genesis, Master System, Game Gear, 32X, SG-1000
- Sony: PSP, PS Vita
- Atari: 2600, 5200, 7800, Lynx, Jaguar, ST
- And many more (ColecoVision, Intellivision, Vectrex, MSX, etc.)

## Troubleshooting

### Duplicate games appearing
Add a title mapping in `normalize_title()`:
```python
title_mappings = {
    'japanese normalized title': 'english normalized title',
}
```

### System not detected
1. Check folder name matches a known alias (`--list-systems`)
2. For flat directories, use `--auto-detect`
3. Add new extension mapping to `EXTENSION_TO_SYSTEM`

### Wrong version selected
Check `_selection_log.txt` for details. Common issues:
- Missing title mapping
- Translation incorrectly detected as hack
- Region priority not matching expectations

## Statistics

| Metric | Value |
|--------|-------|
| Systems supported | 144 |
| DAT files available | 102 |
| Folder aliases | 200+ |
| Title mappings | 1,194 |
| Mapping categories | 50 |
| File extensions | 90+ |

## Supported Systems (144)

Run `python retro-refiner.py --list-systems` for full details.

### Nintendo
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| NES | `.nes` | nes, famicom, fc |
| Famicom Disk System | `.fds` | fds |
| SNES | `.sfc`, `.smc` | snes, super-nes, superfamicom, sfc |
| Nintendo 64 | `.n64`, `.z64`, `.v64` | n64, nintendo64 |
| Nintendo 64DD | `.ndd` | n64dd, 64dd |
| GameCube | `.gcm`, `.gcz`, `.rvz` | gamecube, gc, ngc |
| Wii | `.wbfs`, `.wia` | wii |
| Switch | `.nsp`, `.xci` | switch |
| Game Boy | `.gb` | gameboy, gb |
| Game Boy Color | `.gbc` | gameboy-color, gbc |
| Game Boy Advance | `.gba` | gba |
| Nintendo DS | `.nds`, `.dsi` | nds, ds |
| Nintendo 3DS | `.3ds`, `.cia` | 3ds |
| Virtual Boy | `.vb` | virtualboy, vboy |
| Pokemon Mini | `.min` | pokemini |

### Sega
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| SG-1000 | `.sg` | sg1000 |
| Master System | `.sms` | mastersystem, sms |
| Genesis/Mega Drive | `.md`, `.gen`, `.smd` | genesis, megadrive, md |
| Sega CD | `.cue`, `.chd` | segacd, megacd |
| Sega 32X | `.32x` | sega32x, 32x |
| Saturn | - | saturn, ss |
| Dreamcast | `.gdi`, `.cdi` | dreamcast, dc |
| Game Gear | `.gg` | gamegear |
| Sega Pico | `.pco` | segapico, pico |

### Sony
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| PlayStation | `.iso` | psx, ps1, playstation |
| PlayStation 2 | - | ps2, playstation2 |
| PlayStation 3 | - | ps3, playstation3 |
| PSP | `.pbp`, `.cso` | psp |
| PS Vita | - | psvita, vita |

### Atari
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| Atari 2600 | `.a26` | atari2600, vcs |
| Atari 5200 | `.a52` | atari5200 |
| Atari 7800 | `.a78` | atari7800 |
| Atari 800/XL/XE | `.atr`, `.xex`, `.a8` | atari800 |
| Atari ST | `.st`, `.stx` | atarist |
| Atari Jaguar | `.j64`, `.jag` | atarijaguar, jaguar |
| Atari Lynx | `.lnx` | atarilynx, lynx |

### NEC
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| TurboGrafx-16/PC Engine | `.pce`, `.sgx` | tg16, pcengine, pce |
| TurboGrafx-CD | - | tgcd, pcecd |
| PC-FX | - | pcfx |
| SuperGrafx | - | supergrafx |

### SNK
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| Neo Geo | `.neo` | neogeo |
| Neo Geo CD | - | neogeocd |
| Neo Geo Pocket | `.ngp` | ngp |
| Neo Geo Pocket Color | `.ngc` | ngpc |

### Computers
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| Commodore 64 | `.d64`, `.t64`, `.prg`, `.crt` | c64, commodore64 |
| Amiga | `.adf`, `.adz`, `.ipf`, `.lha` | amiga |
| ZX Spectrum | `.tap`, `.tzx`, `.z80`, `.sna` | zxspectrum, spectrum |
| Amstrad CPC | `.dsk`, `.cdt` | amstradcpc, cpc |
| MSX | `.mx1`, `.rom`, `.cas` | msx |
| MSX2 | `.mx2` | msx2 |
| PC-88 | - | pc88 |
| PC-98 | - | pc98 |
| Sharp X68000 | - | x68000 |
| FM Towns | - | fmtowns |
| Apple II | - | apple2 |
| TRS-80 | - | trs80 |

### Other
| System | Extensions | Folder Aliases |
|--------|-----------|----------------|
| ColecoVision | `.col` | colecovision |
| Intellivision | `.int` | intellivision |
| Vectrex | `.vec` | vectrex |
| Odyssey 2 | `.o2` | odyssey2, videopac |
| Channel F | `.fcf` | channelf, fairchild |
| 3DO | `.3do` | 3do |
| WonderSwan | `.ws` | wonderswan |
| WonderSwan Color | `.wsc` | wonderswan-color |

### Arcade
| System | Folder Aliases |
|--------|----------------|
| MAME | mame, arcade |
| CPS1/CPS2/CPS3 | cps1, cps2, cps3 |
| Naomi | naomi |
| FinalBurn Neo | fbneo, fba |

## Disclaimer

**Retro-Refiner is a file management utility only.** It does not download, host, distribute, or provide access to any copyrighted content, ROMs, games, or proprietary software.

This tool:
- Does **not** include any games, ROMs, BIOS files, or copyrighted material
- Does **not** circumvent copy protection or DRM
- Does **not** facilitate piracy or copyright infringement
- Is functionally equivalent to file managers, search tools, or scripts that organize files by name

Retro-Refiner simply reads filenames and organizes files that already exist on the user's system or network. It performs the same operations as standard file management commands (`cp`, `mv`, `ln`) based on filename pattern matching.

**Users are solely responsible for:**
- Ensuring they have legal rights to any files they process
- Compliance with all applicable laws in their jurisdiction
- How they choose to use this tool

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
