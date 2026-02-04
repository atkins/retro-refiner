# Retro-Refiner

**Refine your ROM collection down to the essentials.**

## Overview
Inspired by the 1G1R (One Game, One ROM) philosophy, Retro-Refiner simplifies the generation of RetroArch-friendly ROM sets. Point it at large ROM archives—local or network—and it automatically selects the best English version of each game. Ideal for grabbing optimized, customized sets from archive sites. Supports 144 systems with 200+ folder aliases.

## Files
- `retro-refiner.py` - Main filtering script
- `title_mappings.json` - External title mappings (315+ Japan→English mappings)
- `update_mappings.py` - Tool to scan archives and suggest new mappings
- `retro-refiner.yaml` - Example configuration file
- `tests/test_selection.py` - Testing helper for verifying game series selection
- `tests/test_bandwidth.py` - Bandwidth benchmark tool for tuning download settings

## Usage

### Basic (current directory)
```bash
python retro-refiner.py
```

### Specify source directory
```bash
python retro-refiner.py -s /path/to/roms
```

### Specify both source and destination
```bash
python retro-refiner.py -s /path/to/roms -d /path/to/output
```

### Process specific systems only
```bash
python retro-refiner.py --systems nes snes genesis
```

### Commit mode: actually transfer files (default is dry run which doesn't copy/move/link/download)
```bash
python retro-refiner.py --commit
```

### List all supported systems
```bash
python retro-refiner.py --list-systems
```

### Clean cache and generated data
```bash
python retro-refiner.py --clean
```

## System Detection

The script supports two modes:

### 1. Folder-based (default)
ROMs organized in system subfolders:
```
roms/
  nes/
  snes/
  genesis/
```
Folder names are normalized (e.g., `megadrive` → `genesis`, `famicom` → `nes`)

### 2. Extension-based (--auto-detect)
For flat directories, detects system from file extensions:
- `.nes`, `.fds` → NES
- `.sfc`, `.smc` → SNES
- `.gb` → Game Boy
- `.gbc` → Game Boy Color
- `.gba` → GBA
- `.n64`, `.z64`, `.v64` → N64
- `.md`, `.gen` → Genesis
- `.sms` → Master System
- `.gg` → Game Gear
- etc.

### 3. Network sources (HTTPS)
Supports fetching ROMs from web servers with HTML directory listings:
```bash
python retro-refiner.py -s https://myserver.com/roms/
```
- Parses Apache/nginx autoindex HTML listings
- Downloads to local cache (`<source>/cache/` or `--cache-dir`)
- Caches files to avoid re-downloading
- Parallel downloads with `--parallel N` (default: 4)
- Uses aria2c (if installed) for best performance, otherwise curl
- Live download progress showing active downloads and recent completions

## Key Concepts

### ROM Naming Convention (No-Intro)
- `Game Title (Region) (Rev X) [Tags].zip`
- Region: USA, Europe, Japan, World, Korea, etc.
- Language: (En), (En,Fr,De), (Japan) (En), etc.
- Special: (Proto), (Beta), (Demo), [T-En by Translator], [Hack by], etc.

### Language Priority (via `--region-priority`)
Default prioritizes English releases (customizable):
1. USA releases (English - highest priority)
2. World releases (Multi-language/English)
3. Europe/Australia releases (English)
4. Fan translations of Japan-only games (when no official English exists)
5. Untranslated Japan-only games (when no English or translation exists)

When combining multiple sources (e.g., No-Intro + T-En Collection):
- Official English releases are preferred over fan translations
- Fan translations are preferred over untranslated foreign ROMs
- This ensures Japan-only games get translations when available

### What Gets Filtered OUT
- Betas, demos, promos, samples
- Re-releases (Virtual Console, Mini consoles, Collections, etc.)
- BIOS files
- Pirate/Unlicensed dumps
- Homebrew
- Compilations (Double Pack, X-in-1, All-Stars, etc.)
- Hacked ROMs (except pure translations)
- Caravan/Taikenban demo versions

### What Gets Included
- Official releases (prefer latest revision)
- Prototypes
- Fan translations [T-En by...]
- Japan-only games when no English version exists

## Configuration File

The script supports YAML configuration files (`retro-refiner.yaml`):

```bash
# Use config from specific path
python retro-refiner.py --config /path/to/config.yaml

# Auto-loads retro-refiner.yaml from source directory if present
python retro-refiner.py -s /roms  # Loads /roms/retro-refiner.yaml if it exists
```

### Key Config Options
```yaml
# Sources (local or network)
source:
  - /path/to/roms
  - https://server.com/roms/

# Destination
dest: /path/to/output

# Language priority
region_priority: "USA,World,Europe,Japan"

# Systems to process
systems:
  - nes
  - snes
  - gba

# Filtering
include:
  - "*Mario*"
  - "*Zelda*"
exclude:
  - "*Beta*"
```

CLI arguments override config file settings.

## Title Mappings

Title mappings are stored in `title_mappings.json` - an external JSON file with 315+ Japan→English mappings organized by series:

### Major Series Covered
- **Pokemon**: Pocket Monsters (Aka/Ao/Midori/Kin/Gin) → Pokemon, all language variants
- **Mega Man**: All Rockman → Mega Man, including EXE/Zero/World series
- **Zelda**: All Zelda no Densetsu titles, Famicom Mini → Classic NES Series
- **Final Fantasy**: FF numbering differences (JP IV = US II, JP VI = US III)
- **Mario**: Super Donkey Kong → DK Country, Hoshi no Kirby → Kirby, regional variants
- **Castlevania**: Akumajou Dracula series, Dracula Densetsu, regional names
- **Contra**: Probotector (EU) mappings, Contra Spirits → Contra III
- **Street Fighter**: Zero → Alpha, regional tournament editions
- **Dragon Quest**: Dragon Warrior mappings
- **Fire Emblem**: All Japanese subtitles to English names
- **TMNT**: Hero Turtles (EU) → Ninja Turtles (USA)
- **Bomberman**: Baku Bomberman → Bomberman 64, regional Max versions
- **Gradius**: Nemesis/Galaxies/Generation variants
- **Kirby**: Hoshi no Kirby → Kirby's Dream Land series

## Common Development Tasks

### Test a game series
```python
from retro-refiner import parse_rom_filename, normalize_title
rom = parse_rom_filename('Pocket Monsters Aka (Japan).zip')
print(normalize_title(rom.base_title))  # → 'pokemon red version'
```

### Add new title mapping
Add to `title_mappings.json` under the appropriate category:
```json
{
  "category_name": {
    "normalized japanese title": "normalized english title"
  }
}
```
Note: Titles should be lowercase, punctuation removed, roman numerals converted to arabic.

### Suggest new mappings automatically
Use `update_mappings.py` to scan archives and suggest mappings:
```bash
python update_mappings.py --scan-myrient gba    # Scan Myrient for GBA
python update_mappings.py --suggest              # Show suggested mappings
python update_mappings.py --merge                # Merge suggestions into mappings
```

### Add new re-release pattern
In `parse_rom_filename()`, add to `rerelease_patterns`:
```python
r'Pattern Name',
```

### Add new compilation pattern
In `parse_rom_filename()`, add to `compilation_patterns`:
```python
r'Pattern',
```

### Add new system extension mapping
In `EXTENSION_TO_SYSTEM` dict at module level:
```python
'.ext': 'system-name',
```

### Add new folder name alias
In `FOLDER_ALIASES` dict at module level:
```python
'folder-name': 'standard-system-name',
```

## Title Mapping Functions

### Key Functions
- `load_title_mappings()` - Load mappings from `title_mappings.json`
- `normalize_title(title)` - Normalize and map titles (lowercase, remove punctuation, apply mappings)

### Mapping File Format
`title_mappings.json` structure:
```json
{
  "pokemon": {
    "pocket monsters aka": "pokemon red version",
    "pocket monsters ao": "pokemon blue version"
  },
  "megaman": {
    "rockman": "mega man",
    "rockman 2": "mega man 2"
  }
}
```

## Network Source Support

### Key Functions
- `is_url(source)` - Check if source is a URL
- `parse_url(url)` - Parse URL into (scheme, host, path) components
- `normalize_url(href, base_url)` - Resolve relative/absolute URLs
- `extract_links_from_html(html)` - Extract all links using multiple patterns
- `is_rom_file(filename)` - Check if filename is a ROM file
- `is_directory_link(href)` - Check if link appears to be a directory
- `parse_html_for_files(html, base_url)` - Extract ROM file URLs from any HTML
- `parse_html_for_directories(html, base_url)` - Extract subdirectory URLs
- `fetch_url(url)` - Fetch content with redirect following, returns (content, final_url)
- `download_file_cached(url, cache_dir)` - Download file with local caching
- `scan_network_source(base_url, cache_dir, systems, recursive, max_depth)` - Scan network source

### Supported Page Formats
- Apache/nginx autoindex directory listings
- Custom HTML pages with download links
- FTP-style text listings in `<pre>` blocks
- Table-based file listings
- Various link formats: href, src, data-url, onclick handlers

### Caching
Downloaded files are stored in `<primary_source>/cache/<system>/filename`.
Files are not re-downloaded if they already exist in cache.

### Download Tools
The script auto-detects and uses the best available download tool:
1. **aria2c** (best) - Parallel downloads + multiple connections per file
2. **curl** (good) - Parallel downloads
3. **Python urllib** (fallback) - Sequential downloads

Install aria2c for best performance with large files:
- macOS: `brew install aria2`
- Linux: `apt install aria2`

### Parallel Downloads
Use `--parallel N` to control concurrent downloads (default: 4):
```bash
python retro-refiner.py -s https://example.com/roms/ --parallel 8 --commit
```

### Auto-Tuning (Default)
Download settings are automatically optimized based on file sizes:

| File Size | Parallel | Connections | Rationale |
|-----------|----------|-------------|-----------|
| < 10 MB   | 8        | 1           | Many small files, minimal per-file overhead |
| 10-100 MB | 8        | 2           | Balanced |
| > 100 MB  | 8        | 4           | Fewer large files, max bandwidth per file |

Auto-tune uses the median file size of the download queue to select settings.

**Disable auto-tuning:**
```bash
python retro-refiner.py -s https://example.com/roms/ --no-auto-tune --parallel 8 --connections 16 --commit
```

**Key Functions:**
- `calculate_autotune_settings(file_sizes)` - Returns optimal (parallel, connections) tuple
- `AUTOTUNE_SMALL_THRESHOLD` - 10 MB threshold
- `AUTOTUNE_LARGE_THRESHOLD` - 100 MB threshold

### Download Error Handling
Downloads include automatic retry and stall detection:

- **Stall detection**: If no file completions AND zero download speed for 60 seconds, the current batch is aborted
- **Automatic retries**: Failed downloads are retried up to 3 times
- **Failure reporting**: Lists all failed files at the end of download

**Key Functions:**
- `DownloadUI._check_stall()` - Detect hung downloads
- `DownloadUI._get_failed_downloads()` - Get retryable failed files
- `DownloadUI._mark_for_retry()` - Reset failed files for retry

### Bandwidth Testing
Use `tests/test_bandwidth.py` to benchmark download performance:
```bash
# Quick test of Myrient
python tests/test_bandwidth.py --site myrient --quick

# Full test of both sites (requires IA credentials for Archive.org)
python tests/test_bandwidth.py --site both --duration 60

# Test only large files
python tests/test_bandwidth.py --size large
```

### Internet Archive Authentication
Archive.org requires authentication to download files. Use S3-style credentials:

**Via command line:**
```bash
python retro-refiner.py \
  -s "https://archive.org/download/sega_saturn/" \
  --ia-access-key YOUR_ACCESS_KEY \
  --ia-secret-key YOUR_SECRET_KEY \
  --commit
```

**Via environment variables (safer, no keys in shell history):**
```bash
export IA_ACCESS_KEY=your_access_key
export IA_SECRET_KEY=your_secret_key
python retro-refiner.py -s "https://archive.org/download/sega_saturn/" --commit
```

Get credentials at: https://archive.org/account/s3.php

**Key Functions:**
- `is_archive_org_url(url)` - Check if URL is from archive.org
- `get_ia_auth_header(access_key, secret_key)` - Build `LOW accesskey:secretkey` auth header

### T-En (Translation) DAT Support
When using T-En translation ROM collections, the script automatically downloads corresponding T-En DAT files from Archive.org for improved ROM matching:

```shell
# Using both official and T-En sources
python retro-refiner.py \
  -s "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy%20Advance/" \
  -s "https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20Advance%20%5BT-En%5D%20Collection/"
```

T-En DAT files are hosted on Archive.org and require authentication. Set `IA_ACCESS_KEY` and `IA_SECRET_KEY` environment variables for T-En DAT support.

**Key Functions:**
- `is_ten_source(url)` - Check if URL is a T-En collection
- `download_ten_dat(system, dest_dir, auth_header)` - Download T-En DAT from Archive.org
- `TEN_DAT_SYSTEMS` - Mapping of system names to T-En DAT file prefixes

## Supported Systems (144)
Run `python retro-refiner.py --list-systems` for full details.

**Nintendo:** nes, fds, snes, n64, n64dd, gamecube, wii, switch, gameboy, gameboy-color, gba, nds, dsi, 3ds, virtualboy, pokemini, satellaview, sufami, ereader
**Sega:** sg1000, mastersystem, genesis, segacd, sega32x, saturn, dreamcast, gamegear, segapico, beena, naomi, naomi2
**Sony:** psx, ps2, ps3, psp, psvita
**Microsoft:** xbox, xbox360
**Atari:** atari2600, atari5200, atari7800, atari800, atarist, atarijaguar, atarijaguarcd, atarilynx
**NEC:** tg16, tgcd, pcfx, supergrafx, pc88, pc98
**SNK:** neogeo, neogeocd, ngp, ngpc
**Computers:** c64, plus4, vic20, amiga, amigacd32, cdtv, zxspectrum, zx81, amstradcpc, msx, msx2, x68000, sharp-x1, enterprise, tvcomputer, apple2, fmtowns, trs80
**Arcade:** mame, cps1, cps2, cps3, naomi, naomi2, fbneo
**Other:** colecovision, intellivision, vectrex, odyssey2, videopac, channelf, 3do, cdi, wonderswan, wonderswan-color, supervision, loopy, pv1000, advision, superacan, studio2, gamecom, scv
**Handhelds:** gp32, gamemaster, pocketchallenge
**Educational:** picno, leappad, leapster, creativision, vsmile
**Mobile:** j2me, palmos, symbian, zeebo

## DAT File Support

### Libretro DAT Integration
Auto-downloads No-Intro and Redump DAT files from libretro-database for ROM verification and metadata.

### Key Functions
- `download_libretro_dat()` - Download DAT for a system
- `parse_clrmamepro_dat()` - Parse ClrMamePro format DAT files
- `calculate_crc32_from_zip()` - Calculate CRC32 of ROM inside ZIP
- `verify_roms_against_dat()` - Verify ROMs against DAT entries

### Adding New Systems
Add to `LIBRETRO_DAT_SYSTEMS` dict:
```python
'system-name': 'Manufacturer - Full DAT Name',
```

### Verification Output
- `_verification_report.txt` in each system folder
- Lists verified, unknown, and bad ROMs

## Arcade Support (MAME & FBNeo)

Both MAME and FBNeo use category-based filtering via shared `catver.ini`. All DAT files are stored in the consolidated `dat_files/` directory.

### Supported Systems
- `mame` - Full MAME arcade (uses MAME DAT)
- `fbneo` - FinalBurn Neo (uses FBNeo DAT)
- `fba`, `arcade` - Aliases for fbneo/mame

### Required Files in dat_files/
- `catver.ini` - Game categories (shared between MAME/FBNeo)
- `MAME 0.284 (arcade).dat` - MAME game metadata
- `FBNeo_Arcade.dat` - FBNeo game metadata

MAME data auto-downloads if missing. Use `--mame-version 0.274` to specify version.

### Key Functions
- `download_mame_data()` - Auto-download catver.ini and MAME XML
- `parse_catver_ini()` - Parse category data
- `parse_mame_dat()` - Parse MAME/FBNeo DAT/XML for game info
- `filter_mame_roms()` - Main arcade filtering (works for both MAME and FBNeo)

### Category Filtering
Edit `MAME_INCLUDE_CATEGORIES` and `MAME_EXCLUDE_CATEGORIES` sets in retro-refiner.py.

### CHD Handling
CHD files are stored in `mame/gamename/game.chd` and copied alongside ROMs.

## Important Notes
- Destination folders are cleared before each run (no stale files)
- Each system gets `_selection_log.txt` with selection details
- Hacked ROMs are deprioritized but included if only option
- Default destination is `refined/` folder in the script directory
- No external dependencies (YAML parsing and progress bars are built-in)
- No hardcoded paths - works on any machine
