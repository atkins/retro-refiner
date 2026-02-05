# Top-N Games Feature Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Filter ROM collections to top N highest-rated games per system using LaunchBox community ratings.

**Architecture:** Download LaunchBox Metadata.xml (~50MB), parse into ratings cache indexed by system/title, inject rating lookup after ROM grouping but before final selection, sort by rating and take top N.

**Tech Stack:** Python stdlib only (xml.etree.ElementTree for parsing, json for cache), consistent with existing codebase.

---

## Task 1: Add CLI Arguments

**Files:**
- Modify: `retro-refiner.py:7115-7122` (after metadata filtering args)

**Step 1: Write test for new arguments**

Add to `tests/test_selection.py` after existing imports (~line 63):

```python
# Top-N filtering
# (Will be imported after implementation)
```

For now, we'll test manually since argparse tests require running main().

**Step 2: Add --top argument**

In `retro-refiner.py`, find line ~7122 (after `--year-to`), add:

```python
    # Top-N filtering
    parser.add_argument('--top', type=int, default=None,
                        help='Keep only top N rated games per system (requires LaunchBox data)')
    parser.add_argument('--include-unrated', action='store_true',
                        help='Include unrated games after rated games when using --top')
```

**Step 3: Verify arguments parse correctly**

Run: `python3 retro-refiner.py --help | grep -A2 "top"`

Expected output:
```
  --top TOP             Keep only top N rated games per system (requires LaunchBox data)
  --include-unrated     Include unrated games after rated games when using --top
```

**Step 4: Commit**

```bash
git add retro-refiner.py
git commit -m "$(cat <<'EOF'
feat: add --top and --include-unrated CLI arguments

Adds argument parsing for top-N games feature. Implementation pending.
EOF
)"
```

---

## Task 2: Add LaunchBox Platform Mapping

**Files:**
- Modify: `retro-refiner.py` (after `LIBRETRO_DAT_SYSTEMS` ~line 3864)

**Step 1: Write test for platform mapping**

Add to `tests/test_selection.py` in the system detection section (~line 550):

```python
def test_launchbox_platform_mapping():
    """Test LaunchBox platform names map to retro-refiner system codes."""
    print("\n" + "="*60)
    print("LAUNCHBOX PLATFORM MAPPING TESTS")
    print("="*60)

    # Import after implementation
    try:
        LAUNCHBOX_PLATFORM_MAP = _module.LAUNCHBOX_PLATFORM_MAP
    except AttributeError:
        print("  [SKIP] LAUNCHBOX_PLATFORM_MAP not yet implemented")
        return

    test_cases = [
        ("Super Nintendo Entertainment System", "snes"),
        ("Nintendo Entertainment System", "nes"),
        ("Sega Genesis", "genesis"),
        ("Sega Mega Drive", "genesis"),
        ("Sony Playstation", "psx"),
        ("Nintendo Game Boy Advance", "gba"),
    ]

    for launchbox_name, expected_system in test_cases:
        actual = LAUNCHBOX_PLATFORM_MAP.get(launchbox_name)
        if actual == expected_system:
            results.ok(f"Platform mapping: {launchbox_name} -> {expected_system}")
        else:
            results.fail(f"Platform mapping: {launchbox_name}", expected_system, actual)
```

**Step 2: Run test to verify it skips (not yet implemented)**

Run: `python3 tests/test_selection.py 2>&1 | grep -A2 "LAUNCHBOX"`

Expected: `[SKIP] LAUNCHBOX_PLATFORM_MAP not yet implemented`

**Step 3: Add platform mapping constant**

In `retro-refiner.py`, after `DAT_NAME_TO_SYSTEM` (~line 3864), add:

```python
# LaunchBox platform names to retro-refiner system codes
LAUNCHBOX_PLATFORM_MAP = {
    # Nintendo consoles
    "Nintendo Entertainment System": "nes",
    "Nintendo Famicom Disk System": "fds",
    "Super Nintendo Entertainment System": "snes",
    "Nintendo 64": "n64",
    "Nintendo 64DD": "n64dd",
    "Nintendo GameCube": "gamecube",
    "Nintendo Wii": "wii",
    "Nintendo Wii U": "wiiu",
    "Nintendo Switch": "switch",
    # Nintendo handhelds
    "Nintendo Game Boy": "gameboy",
    "Nintendo Game Boy Color": "gameboy-color",
    "Nintendo Game Boy Advance": "gba",
    "Nintendo DS": "nds",
    "Nintendo DSi": "dsi",
    "Nintendo 3DS": "3ds",
    "Nintendo Virtual Boy": "virtualboy",
    "Nintendo Pokemon Mini": "pokemini",
    # Sega consoles
    "Sega SG-1000": "sg1000",
    "Sega Master System": "mastersystem",
    "Sega Genesis": "genesis",
    "Sega Mega Drive": "genesis",
    "Sega CD": "segacd",
    "Sega 32X": "sega32x",
    "Sega Saturn": "saturn",
    "Sega Dreamcast": "dreamcast",
    # Sega handhelds
    "Sega Game Gear": "gamegear",
    # Sony
    "Sony Playstation": "psx",
    "Sony Playstation 2": "ps2",
    "Sony Playstation 3": "ps3",
    "Sony PSP": "psp",
    "Sony Playstation Vita": "psvita",
    # Microsoft
    "Microsoft Xbox": "xbox",
    "Microsoft Xbox 360": "xbox360",
    # Atari
    "Atari 2600": "atari2600",
    "Atari 5200": "atari5200",
    "Atari 7800": "atari7800",
    "Atari Lynx": "atarilynx",
    "Atari Jaguar": "atarijaguar",
    "Atari Jaguar CD": "atarijaguarcd",
    "Atari ST": "atarist",
    # NEC
    "NEC TurboGrafx-16": "tg16",
    "NEC TurboGrafx-CD": "tgcd",
    "NEC PC-FX": "pcfx",
    "NEC SuperGrafx": "supergrafx",
    "NEC PC-8801": "pc88",
    "NEC PC-9801": "pc98",
    # SNK
    "SNK Neo Geo AES": "neogeo",
    "SNK Neo Geo MVS": "neogeo",
    "SNK Neo Geo CD": "neogeocd",
    "SNK Neo Geo Pocket": "ngp",
    "SNK Neo Geo Pocket Color": "ngpc",
    # Other consoles
    "3DO Interactive Multiplayer": "3do",
    "Philips CD-i": "cdi",
    "Mattel Intellivision": "intellivision",
    "ColecoVision": "colecovision",
    "GCE Vectrex": "vectrex",
    "Magnavox Odyssey 2": "odyssey2",
    "Bandai WonderSwan": "wonderswan",
    "Bandai WonderSwan Color": "wonderswan-color",
    # Arcade
    "Arcade": "mame",
    "MAME": "mame",
    # Computers
    "Commodore 64": "c64",
    "Commodore Amiga": "amiga",
    "Sinclair ZX Spectrum": "zxspectrum",
    "MSX": "msx",
    "MSX2": "msx2",
    "Sharp X68000": "x68000",
}

# Reverse mapping for lookups
SYSTEM_TO_LAUNCHBOX = {}
for lb_name, system in LAUNCHBOX_PLATFORM_MAP.items():
    if system not in SYSTEM_TO_LAUNCHBOX:
        SYSTEM_TO_LAUNCHBOX[system] = lb_name
```

**Step 4: Run test to verify it passes**

Run: `python3 tests/test_selection.py 2>&1 | grep "Platform mapping"`

Expected: All `[PASS]` lines

**Step 5: Commit**

```bash
git add retro-refiner.py tests/test_selection.py
git commit -m "$(cat <<'EOF'
feat: add LaunchBox platform name mapping

Maps LaunchBox platform names (e.g., "Super Nintendo Entertainment System")
to retro-refiner system codes (e.g., "snes"). Covers 70+ platforms.
EOF
)"
```

---

## Task 3: Implement LaunchBox Download Function

**Files:**
- Modify: `retro-refiner.py` (after `download_teknoparrot_dat` ~line 5660)

**Step 1: Write test for download function**

Add to `tests/test_selection.py`:

```python
def test_launchbox_download_function_exists():
    """Test LaunchBox download function exists."""
    print("\n" + "="*60)
    print("LAUNCHBOX DOWNLOAD TESTS")
    print("="*60)

    try:
        download_launchbox_data = _module.download_launchbox_data
        results.ok("download_launchbox_data function exists")
    except AttributeError:
        results.fail("download_launchbox_data function exists", "function", "not found")
        return

    # Test that it returns expected structure (without actually downloading)
    import inspect
    sig = inspect.signature(download_launchbox_data)
    params = list(sig.parameters.keys())

    if 'dat_dir' in params:
        results.ok("download_launchbox_data has dat_dir parameter")
    else:
        results.fail("download_launchbox_data has dat_dir parameter", "dat_dir", params)
```

**Step 2: Run test to verify it fails**

Run: `python3 tests/test_selection.py 2>&1 | grep -A1 "download_launchbox"`

Expected: `[FAIL]`

**Step 3: Implement download function**

In `retro-refiner.py`, after `download_teknoparrot_dat` function (~line 5660), add:

```python
LAUNCHBOX_METADATA_URL = "http://gamesdb.launchbox-app.com/Metadata.zip"

def download_launchbox_data(dat_dir: Path, force: bool = False) -> Optional[Path]:
    """Download LaunchBox Metadata.xml for game ratings.

    Args:
        dat_dir: Directory to store downloaded files
        force: Re-download even if file exists

    Returns:
        Path to Metadata.xml or None if download failed
    """
    launchbox_dir = dat_dir / "launchbox"
    launchbox_dir.mkdir(parents=True, exist_ok=True)

    xml_path = launchbox_dir / "Metadata.xml"
    zip_path = launchbox_dir / "Metadata.zip"

    # Skip if already exists and not forcing
    if xml_path.exists() and not force:
        Console.detail(f"LaunchBox data exists: {xml_path}")
        return xml_path

    Console.info(f"Downloading LaunchBox metadata (~50MB)...")

    try:
        # Download zip file
        req = urllib.request.Request(
            LAUNCHBOX_METADATA_URL,
            headers={'User-Agent': 'Retro-Refiner/1.0'}
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(zip_path, 'wb') as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        print(f"\r  Downloading: {format_size(downloaded)} / {format_size(total_size)} ({pct:.1f}%)", end='', flush=True)
            print()  # Newline after progress

        Console.success(f"Downloaded {format_size(downloaded)}")

        # Extract Metadata.xml from zip
        Console.info("Extracting Metadata.xml...")
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extract('Metadata.xml', launchbox_dir)

        # Remove zip to save space
        zip_path.unlink()

        Console.success(f"LaunchBox data ready: {xml_path}")
        return xml_path

    except Exception as e:
        Console.error(f"Failed to download LaunchBox data: {e}")
        # Clean up partial downloads
        if zip_path.exists():
            zip_path.unlink()
        return None
```

**Step 4: Run test to verify it passes**

Run: `python3 tests/test_selection.py 2>&1 | grep "download_launchbox"`

Expected: `[PASS]`

**Step 5: Commit**

```bash
git add retro-refiner.py tests/test_selection.py
git commit -m "$(cat <<'EOF'
feat: add download_launchbox_data function

Downloads LaunchBox Metadata.xml from gamesdb.launchbox-app.com.
Shows progress during download, extracts XML from zip, cleans up.
EOF
)"
```

---

## Task 4: Implement Ratings Cache Builder

**Files:**
- Modify: `retro-refiner.py` (after `download_launchbox_data`)

**Step 1: Write test for cache builder**

Add to `tests/test_selection.py`:

```python
def test_build_ratings_cache():
    """Test building ratings cache from sample XML."""
    print("\n" + "="*60)
    print("RATINGS CACHE TESTS")
    print("="*60)

    try:
        build_ratings_cache = _module.build_ratings_cache
    except AttributeError:
        print("  [SKIP] build_ratings_cache not yet implemented")
        return

    # Create sample XML
    sample_xml = '''<?xml version="1.0" encoding="utf-8"?>
<LaunchBox>
  <Game>
    <Name>Super Mario World</Name>
    <Platform>Super Nintendo Entertainment System</Platform>
    <CommunityRating>4.73</CommunityRating>
    <CommunityRatingCount>892</CommunityRatingCount>
  </Game>
  <Game>
    <Name>Sonic the Hedgehog</Name>
    <Platform>Sega Genesis</Platform>
    <CommunityRating>4.21</CommunityRating>
    <CommunityRatingCount>456</CommunityRatingCount>
  </Game>
  <Game>
    <Name>No Rating Game</Name>
    <Platform>Super Nintendo Entertainment System</Platform>
  </Game>
</LaunchBox>'''

    # Write to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
        f.write(sample_xml)
        temp_path = Path(f.name)

    try:
        cache = build_ratings_cache(temp_path)

        # Check SNES entries
        if 'snes' in cache:
            results.ok("Cache contains snes platform")
        else:
            results.fail("Cache contains snes platform", "snes in cache", list(cache.keys()))
            return

        # Check normalized title lookup
        if 'super mario world' in cache['snes']:
            results.ok("Cache contains normalized title 'super mario world'")
        else:
            results.fail("Cache contains normalized title", "super mario world", list(cache['snes'].keys()))

        # Check rating value
        rating_entry = cache['snes'].get('super mario world', {})
        if rating_entry.get('rating') == 4.73:
            results.ok("Rating value correct (4.73)")
        else:
            results.fail("Rating value", 4.73, rating_entry.get('rating'))

        # Check votes
        if rating_entry.get('votes') == 892:
            results.ok("Vote count correct (892)")
        else:
            results.fail("Vote count", 892, rating_entry.get('votes'))

        # Check genesis
        if 'genesis' in cache and 'sonic the hedgehog' in cache['genesis']:
            results.ok("Cache contains genesis/sonic")
        else:
            results.fail("Cache contains genesis/sonic", True, False)

    finally:
        temp_path.unlink()
```

**Step 2: Run test to verify it skips**

Run: `python3 tests/test_selection.py 2>&1 | grep -A1 "RATINGS CACHE"`

Expected: `[SKIP] build_ratings_cache not yet implemented`

**Step 3: Implement cache builder**

In `retro-refiner.py`, after `download_launchbox_data`:

```python
def build_ratings_cache(xml_path: Path, cache_path: Path = None) -> dict:
    """Parse LaunchBox Metadata.xml and build ratings cache.

    Args:
        xml_path: Path to Metadata.xml
        cache_path: Optional path to save JSON cache

    Returns:
        Dict of {system: {normalized_title: {"rating": float, "votes": int}}}
    """
    import xml.etree.ElementTree as ET

    Console.info(f"Building ratings cache from {xml_path.name}...")

    cache = {}
    game_count = 0
    rated_count = 0

    # Use iterparse for memory efficiency with large XML
    context = ET.iterparse(str(xml_path), events=('end',))

    for event, elem in context:
        if elem.tag == 'Game':
            name = elem.findtext('Name')
            platform = elem.findtext('Platform')
            rating_str = elem.findtext('CommunityRating')
            votes_str = elem.findtext('CommunityRatingCount')

            if name and platform:
                game_count += 1

                # Map platform to our system code
                system = LAUNCHBOX_PLATFORM_MAP.get(platform)
                if not system:
                    elem.clear()
                    continue

                # Only include games with ratings
                if rating_str and votes_str:
                    try:
                        rating = float(rating_str)
                        votes = int(votes_str)

                        # Normalize title for matching
                        normalized = normalize_title(name)

                        if system not in cache:
                            cache[system] = {}

                        # Keep highest-voted entry if duplicate titles
                        existing = cache[system].get(normalized)
                        if not existing or votes > existing['votes']:
                            cache[system][normalized] = {
                                'rating': rating,
                                'votes': votes,
                                'name': name  # Keep original for debugging
                            }

                        rated_count += 1
                    except (ValueError, TypeError):
                        pass

            # Clear element to free memory
            elem.clear()

    Console.success(f"Parsed {game_count} games, {rated_count} with ratings")

    # Save cache if path provided
    if cache_path:
        Console.info(f"Saving ratings cache to {cache_path.name}...")
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
        Console.success(f"Cache saved ({format_size(cache_path.stat().st_size)})")

    return cache


def load_ratings_cache(dat_dir: Path, force_rebuild: bool = False) -> dict:
    """Load ratings cache, building from XML if needed.

    Args:
        dat_dir: Directory containing launchbox/ subfolder
        force_rebuild: Force rebuild even if cache exists

    Returns:
        Ratings cache dict or empty dict if unavailable
    """
    launchbox_dir = dat_dir / "launchbox"
    xml_path = launchbox_dir / "Metadata.xml"
    cache_path = launchbox_dir / "ratings_cache.json"

    # Check if we have the XML
    if not xml_path.exists():
        return {}

    # Check if cache is newer than XML
    if cache_path.exists() and not force_rebuild:
        if cache_path.stat().st_mtime >= xml_path.stat().st_mtime:
            Console.detail(f"Loading ratings cache from {cache_path.name}...")
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                Console.warning("Cache corrupted, rebuilding...")

    # Build cache from XML
    return build_ratings_cache(xml_path, cache_path)
```

**Step 4: Run test to verify it passes**

Run: `python3 tests/test_selection.py 2>&1 | grep -E "(Rating|Vote|Cache contains)"`

Expected: All `[PASS]` lines

**Step 5: Commit**

```bash
git add retro-refiner.py tests/test_selection.py
git commit -m "$(cat <<'EOF'
feat: add build_ratings_cache and load_ratings_cache

Parses LaunchBox Metadata.xml using iterparse for memory efficiency.
Builds JSON cache indexed by system/normalized_title.
Cache auto-rebuilds if XML is newer than cache file.
EOF
)"
```

---

## Task 5: Implement Top-N Filter Function

**Files:**
- Modify: `retro-refiner.py` (after `load_ratings_cache`)

**Step 1: Write test for top-N filtering**

Add to `tests/test_selection.py`:

```python
def test_apply_top_n_filter():
    """Test top-N filtering logic."""
    print("\n" + "="*60)
    print("TOP-N FILTER TESTS")
    print("="*60)

    try:
        apply_top_n_filter = _module.apply_top_n_filter
    except AttributeError:
        print("  [SKIP] apply_top_n_filter not yet implemented")
        return

    # Create sample ROMs
    roms = [
        RomInfo(filename="Game A (USA).zip", base_title="Game A", region="USA",
                revision=0, languages=["En"], is_english=True),
        RomInfo(filename="Game B (USA).zip", base_title="Game B", region="USA",
                revision=0, languages=["En"], is_english=True),
        RomInfo(filename="Game C (USA).zip", base_title="Game C", region="USA",
                revision=0, languages=["En"], is_english=True),
        RomInfo(filename="Unrated Game (USA).zip", base_title="Unrated Game", region="USA",
                revision=0, languages=["En"], is_english=True),
    ]

    # Sample ratings (higher = better)
    ratings = {
        'game a': {'rating': 4.5, 'votes': 100},
        'game b': {'rating': 3.0, 'votes': 50},
        'game c': {'rating': 4.8, 'votes': 200},
        # 'unrated game' intentionally missing
    }

    # Test 1: Top 2, no unrated
    result = apply_top_n_filter(roms, ratings, top_n=2, include_unrated=False)
    titles = [r.base_title for r in result]

    if len(result) == 2:
        results.ok("Top 2 returns 2 games")
    else:
        results.fail("Top 2 returns 2 games", 2, len(result))

    # Should be C (4.8) then A (4.5)
    if titles == ['Game C', 'Game A']:
        results.ok("Top 2 sorted by rating (C=4.8, A=4.5)")
    else:
        results.fail("Top 2 sorted by rating", ['Game C', 'Game A'], titles)

    # Test 2: Top 3 with unrated included
    result = apply_top_n_filter(roms, ratings, top_n=4, include_unrated=True)
    titles = [r.base_title for r in result]

    if len(result) == 4:
        results.ok("Top 4 with unrated returns 4 games")
    else:
        results.fail("Top 4 with unrated returns 4 games", 4, len(result))

    # Unrated should be last
    if titles[-1] == 'Unrated Game':
        results.ok("Unrated game appears last")
    else:
        results.fail("Unrated game appears last", 'Unrated Game', titles[-1])

    # Test 3: Top 2, exclude unrated (should only get rated games)
    result = apply_top_n_filter(roms, ratings, top_n=5, include_unrated=False)
    if len(result) == 3:  # Only 3 rated games exist
        results.ok("Without include_unrated, only rated games returned")
    else:
        results.fail("Without include_unrated, only rated games returned", 3, len(result))
```

**Step 2: Run test to verify it skips**

Run: `python3 tests/test_selection.py 2>&1 | grep -A1 "TOP-N FILTER"`

Expected: `[SKIP] apply_top_n_filter not yet implemented`

**Step 3: Implement top-N filter**

In `retro-refiner.py`, after `load_ratings_cache`:

```python
def apply_top_n_filter(roms: List[RomInfo], ratings: dict, top_n: int,
                       include_unrated: bool = False) -> List[RomInfo]:
    """Filter ROMs to top N by rating.

    Args:
        roms: List of RomInfo objects (already selected best per game)
        ratings: Dict of {normalized_title: {"rating": float, "votes": int}}
        top_n: Number of top games to keep
        include_unrated: If True, append unrated games after rated ones

    Returns:
        Filtered list of RomInfo, sorted by rating descending
    """
    rated_roms = []
    unrated_roms = []

    for rom in roms:
        normalized = normalize_title(rom.base_title)
        rating_entry = ratings.get(normalized)

        if rating_entry:
            rated_roms.append((rom, rating_entry['rating'], rating_entry['votes']))
        else:
            unrated_roms.append(rom)

    # Sort rated ROMs by rating (desc), then by votes (desc) for ties
    rated_roms.sort(key=lambda x: (-x[1], -x[2]))

    # Take top N rated
    result = [rom for rom, rating, votes in rated_roms[:top_n]]

    # If including unrated and we have room, append them
    if include_unrated and len(result) < top_n:
        remaining_slots = top_n - len(result)
        result.extend(unrated_roms[:remaining_slots])

    return result
```

**Step 4: Run test to verify it passes**

Run: `python3 tests/test_selection.py 2>&1 | grep -E "(Top|Unrated|rated games)"`

Expected: All `[PASS]` lines

**Step 5: Commit**

```bash
git add retro-refiner.py tests/test_selection.py
git commit -m "$(cat <<'EOF'
feat: add apply_top_n_filter function

Filters ROMs to top N by LaunchBox rating. Sorts by rating descending,
uses vote count as tiebreaker. Unrated games appended at end if
--include-unrated flag is set.
EOF
)"
```

---

## Task 6: Integrate Top-N into filter_roms_from_files

**Files:**
- Modify: `retro-refiner.py:6930-6965` (after ROM selection, before transfer)

**Step 1: Add top_n and include_unrated parameters to function signature**

Find `filter_roms_from_files` (~line 6811) and update signature:

```python
def filter_roms_from_files(rom_files: list, dest_dir: str, system: str, dry_run: bool = False,
                           dat_entries: Dict[str, DatRomEntry] = None,
                           include_patterns: List[str] = None,
                           exclude_patterns: List[str] = None,
                           exclude_protos: bool = False,
                           include_betas: bool = False,
                           include_unlicensed: bool = False,
                           region_priority: List[str] = None,
                           keep_regions: List[str] = None,
                           flat_output: bool = False,
                           transfer_mode: str = 'copy',
                           year_from: int = None,
                           year_to: int = None,
                           verbose: bool = False,
                           top_n: int = None,
                           include_unrated: bool = False,
                           ratings: dict = None):
```

**Step 2: Add top-N filtering after ROM selection**

Find the section after `selected_roms` is populated (~line 6963), before size calculation. Add:

```python
    # Apply top-N filter if requested
    if top_n and ratings:
        system_ratings = ratings.get(system, {})
        pre_filter_count = len(selected_roms)

        rated_count = sum(1 for r in selected_roms
                        if normalize_title(r.base_title) in system_ratings)

        print(f"{system.upper()}: Rating data matched {rated_count} of {pre_filter_count} games")

        selected_roms = apply_top_n_filter(
            selected_roms, system_ratings, top_n, include_unrated
        )

        filtered_out = pre_filter_count - len(selected_roms)
        if include_unrated:
            print(f"{system.upper()}: Top {top_n} selected ({filtered_out} below cutoff)")
        else:
            unrated_excluded = pre_filter_count - rated_count
            print(f"{system.upper()}: Top {top_n} selected ({filtered_out} below cutoff, {unrated_excluded} unrated excluded)")
```

**Step 3: Update selection log to include ratings**

Find the selection log writing section (~line 7011), update to include ratings:

```python
        f.write("SELECTED ROMS:\n")
        f.write("-" * 60 + "\n")
        for i, rom in enumerate(sorted(selected_roms, key=lambda r: r.base_title.lower()), 1):
            # Get rating if available
            rating_str = ""
            if ratings and system in ratings:
                normalized = normalize_title(rom.base_title)
                rating_entry = ratings[system].get(normalized)
                if rating_entry:
                    rating_str = f" [★{rating_entry['rating']:.2f} ({rating_entry['votes']} votes)]"

            f.write(f"{rom.filename}{rating_str}\n")
            f.write(f"  Title: {rom.base_title}\n")
            f.write(f"  Region: {rom.region}, Rev: {rom.revision}")
            if rom.is_translation:
                f.write(f", Translation: Yes")
            if rom.is_proto:
                f.write(f", Prototype: Yes")
            f.write("\n\n")
```

**Step 4: Verify by running help and checking code compiles**

Run: `python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('rr', 'retro-refiner.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print('OK')"`

Expected: `OK`

**Step 5: Commit**

```bash
git add retro-refiner.py
git commit -m "$(cat <<'EOF'
feat: integrate top-N filtering into filter_roms_from_files

Adds top_n, include_unrated, and ratings parameters. Applies top-N
filter after ROM selection but before file transfer. Updates selection
log to include ratings when available.
EOF
)"
```

---

## Task 7: Wire Up in main()

**Files:**
- Modify: `retro-refiner.py` main() function (~line 7034+)

**Step 1: Add LaunchBox download to --update-dats**

Find the `--update-dats` handling section (~line 7230), add after existing DAT downloads:

```python
        # LaunchBox ratings data
        Console.section("LaunchBox Ratings Data")
        lb_result = download_launchbox_data(dat_dir, force=True)
        if lb_result:
            # Rebuild cache
            load_ratings_cache(dat_dir, force_rebuild=True)
```

**Step 2: Load ratings when --top is used**

Find where systems are processed in main(), before the system loop. Add ratings loading:

```python
    # Load ratings if --top is used
    ratings = {}
    if args.top:
        Console.section("Loading Rating Data")
        dat_dir = Path(args.dat_dir) if args.dat_dir else Path(__file__).parent / 'dat_files'

        # Check if LaunchBox data exists
        lb_xml = dat_dir / "launchbox" / "Metadata.xml"
        if not lb_xml.exists():
            Console.warning("LaunchBox data not found. Downloading...")
            if not download_launchbox_data(dat_dir):
                Console.error("Failed to download LaunchBox data. --top requires rating data.")
                Console.info("Run with --update-dats to download, or remove --top flag.")
                sys.exit(1)

        ratings = load_ratings_cache(dat_dir)
        if not ratings:
            Console.error("Failed to load ratings cache.")
            sys.exit(1)

        total_rated = sum(len(games) for games in ratings.values())
        Console.success(f"Loaded ratings for {total_rated} games across {len(ratings)} systems")
```

**Step 3: Pass top_n and ratings to filter functions**

Find where `filter_roms_from_files` is called and add the new parameters:

```python
                    selected, stats = filter_roms_from_files(
                        rom_files, dest_dir, system,
                        dry_run=not args.commit,
                        dat_entries=dat_entries,
                        include_patterns=args.include,
                        exclude_patterns=args.exclude,
                        exclude_protos=args.exclude_protos,
                        include_betas=args.include_betas,
                        include_unlicensed=args.include_unlicensed,
                        region_priority=region_priority,
                        keep_regions=keep_regions,
                        flat_output=args.flat,
                        transfer_mode=transfer_mode,
                        year_from=args.year_from,
                        year_to=args.year_to,
                        verbose=args.verbose,
                        top_n=args.top,
                        include_unrated=args.include_unrated,
                        ratings=ratings,
                    )
```

**Step 4: Test with dry run**

Run: `python3 retro-refiner.py --help | grep -A2 "top\|unrated"`

Expected: Shows both `--top` and `--include-unrated` options

**Step 5: Commit**

```bash
git add retro-refiner.py
git commit -m "$(cat <<'EOF'
feat: wire up top-N filtering in main()

- Downloads LaunchBox data with --update-dats
- Auto-downloads on first --top use if missing
- Loads ratings cache and passes to filter functions
- Reports rating coverage statistics
EOF
)"
```

---

## Task 8: Update filter_network_roms for Top-N

**Files:**
- Modify: `retro-refiner.py:3103` (filter_network_roms function)

**Step 1: Add parameters to filter_network_roms signature**

Find `filter_network_roms` (~line 3103) and add the same parameters:

```python
def filter_network_roms(rom_urls: List[str], system: str,
                        include_patterns: List[str] = None,
                        exclude_patterns: List[str] = None,
                        exclude_protos: bool = False,
                        include_betas: bool = False,
                        include_unlicensed: bool = False,
                        region_priority: List[str] = None,
                        keep_regions: List[str] = None,
                        year_from: int = None,
                        year_to: int = None,
                        verbose: bool = False,
                        top_n: int = None,
                        include_unrated: bool = False,
                        ratings: dict = None) -> List[Tuple[str, RomInfo]]:
```

**Step 2: Add top-N filtering logic (similar to filter_roms_from_files)**

Find the return statement in filter_network_roms and add before it:

```python
    # Apply top-N filter if requested
    if top_n and ratings:
        system_ratings = ratings.get(system, {})
        pre_filter_count = len(selected)

        # Extract just RomInfo objects for filtering
        selected_roms = [rom_info for url, rom_info in selected]
        url_map = {rom_info.filename: url for url, rom_info in selected}

        rated_count = sum(1 for r in selected_roms
                        if normalize_title(r.base_title) in system_ratings)

        print(f"{system.upper()}: Rating data matched {rated_count} of {pre_filter_count} games")

        filtered_roms = apply_top_n_filter(
            selected_roms, system_ratings, top_n, include_unrated
        )

        # Rebuild selected with URLs
        selected = [(url_map[r.filename], r) for r in filtered_roms]

        filtered_out = pre_filter_count - len(selected)
        print(f"{system.upper()}: Top {top_n} selected ({filtered_out} filtered out)")
```

**Step 3: Update call sites in main() for network sources**

Find where `filter_network_roms` is called and add the parameters.

**Step 4: Verify code compiles**

Run: `python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('rr', 'retro-refiner.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print('OK')"`

Expected: `OK`

**Step 5: Commit**

```bash
git add retro-refiner.py
git commit -m "$(cat <<'EOF'
feat: add top-N support to filter_network_roms

Network sources now support --top filtering same as local sources.
EOF
)"
```

---

## Task 9: Add Config File Support

**Files:**
- Modify: `retro-refiner.py` config loading section

**Step 1: Add config keys to apply_config_to_args**

Find `apply_config_to_args` function and add:

```python
    # Top-N filtering
    if 'top' in config and args.top is None:
        args.top = config['top']
    if 'include_unrated' in config and not args.include_unrated:
        args.include_unrated = config['include_unrated']
```

**Step 2: Update generate_default_config**

Find `generate_default_config` and add to the output:

```python
# Top-N filtering (keep only highest-rated games)
# top: 50                    # Keep top 50 rated games per system
# include_unrated: false     # Include unrated games after rated ones
```

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "$(cat <<'EOF'
feat: add top and include_unrated to config file support

Config file can now specify:
  top: 50
  include_unrated: false
EOF
)"
```

---

## Task 10: Update CLAUDE.md Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add top-N section to CLAUDE.md**

Find the "Usage" section and add examples:

```markdown
### Top-N filtering (highest-rated games)
```bash
# Top 50 rated games per system
python retro-refiner.py -s /path/to/roms --top 50 --commit

# Top 25 Mario games by rating
python retro-refiner.py -s /path/to/roms --top 25 --include "*Mario*" --commit

# Top 100, include unrated games if slots remain
python retro-refiner.py -s /path/to/roms --top 100 --include-unrated --commit
```

Ratings data from LaunchBox (auto-downloaded on first use, refresh with `--update-dats`).
```

**Step 2: Add to Key Concepts section**

```markdown
### Top-N Rating Filter
- Uses LaunchBox community ratings (0-5 scale)
- Data stored in `dat_files/launchbox/`
- `--top N` keeps N highest-rated games per system
- `--include-unrated` adds unrated games after rated ones
- Filters apply before top-N (e.g., `--top 50 --include "*Mario*"` = top 50 Mario games)
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: add top-N filtering documentation to CLAUDE.md

Documents --top and --include-unrated options with examples.
EOF
)"
```

---

## Task 11: Run Full Test Suite

**Step 1: Run all tests**

Run: `python3 tests/test_selection.py`

Expected: All tests pass, `Results: N/N passed`

**Step 2: Manual integration test (dry run)**

Run: `python3 retro-refiner.py -s . --systems nes --top 10 2>&1 | head -50`

Expected: Shows rating loading, no errors

**Step 3: Commit any fixes if needed**

---

## Task 12: Final Review and Merge Prep

**Step 1: Review all changes**

Run: `git log --oneline feature/top-n-games ^master`

**Step 2: Ensure clean test run**

Run: `python3 tests/test_selection.py`

**Step 3: Ready for merge**

Feature complete. Use `superpowers:finishing-a-development-branch` to complete.
