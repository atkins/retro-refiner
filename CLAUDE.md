# Retro-Refiner

**Refine your ROM collection down to the essentials.**

## Overview
Inspired by the 1G1R (One Game, One ROM) philosophy, Retro-Refiner simplifies the generation of RetroArch-friendly ROM sets. Point it at large ROM archives—local or network—and it automatically selects the best English version of each game. Ideal for grabbing optimized, customized sets from archive sites. Supports 144 systems with 200+ folder aliases.

## Files
- `retro-refiner.py` - Main filtering script with 315+ title mappings
- `test_selection.py` - Testing helper for verifying game series selection

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

## Title Mapping Categories

The script has 315+ mappings organized by series:

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
In `normalize_title()`, add to `title_mappings` dict:
```python
'normalized japanese title': 'normalized english title',
```
Note: Titles are already lowercased, punctuation removed, roman numerals converted.

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
