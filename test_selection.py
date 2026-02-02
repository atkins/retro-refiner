#!/usr/bin/env python3
"""
Comprehensive test script for Retro-Refiner.

Tests all major features:
- ROM parsing and selection
- Config file handling
- Network source URL parsing
- Filtering (patterns, regions, year, proto/beta)
- Playlist generation
- Transfer modes
"""

import os
import sys
import json
import tempfile
import importlib.util
from pathlib import Path
from collections import defaultdict

# Import from retro-refiner (using importlib since module name has hyphen)
_spec = importlib.util.spec_from_file_location("retro_refiner", Path(__file__).parent / "retro-refiner.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

# Core parsing
parse_rom_filename = _module.parse_rom_filename
normalize_title = _module.normalize_title
select_best_rom = _module.select_best_rom
RomInfo = _module.RomInfo
DEFAULT_REGION_PRIORITY = _module.DEFAULT_REGION_PRIORITY

# Config handling
load_config = _module.load_config
generate_default_config = _module.generate_default_config
apply_config_to_args = _module.apply_config_to_args
YAML_AVAILABLE = _module.YAML_AVAILABLE

# Network source functions
is_url = _module.is_url
parse_url = _module.parse_url
normalize_url = _module.normalize_url
extract_links_from_html = _module.extract_links_from_html
parse_html_for_files = _module.parse_html_for_files
parse_html_for_directories = _module.parse_html_for_directories
is_rom_file = _module.is_rom_file
is_directory_link = _module.is_directory_link
get_filename_from_url = _module.get_filename_from_url
ROM_EXTENSIONS = _module.ROM_EXTENSIONS

# Filtering
matches_patterns = _module.matches_patterns
filter_network_roms = _module.filter_network_roms

# Playlist generation
generate_m3u_playlist = _module.generate_m3u_playlist
generate_gamelist_xml = _module.generate_gamelist_xml

# System detection
KNOWN_SYSTEMS = _module.KNOWN_SYSTEMS
FOLDER_ALIASES = _module.FOLDER_ALIASES
EXTENSION_TO_SYSTEM = _module.EXTENSION_TO_SYSTEM


class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name):
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, expected, actual):
        self.failed += 1
        self.errors.append((name, expected, actual))
        print(f"  [FAIL] {name}")
        print(f"    Expected: {expected}")
        print(f"    Actual:   {actual}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"Failed tests: {self.failed}")
        print(f"{'='*60}")
        return self.failed == 0


results = TestResult()


# =============================================================================
# ROM Parsing Tests
# =============================================================================

def test_rom_parsing():
    """Test ROM filename parsing."""
    print("\n" + "="*60)
    print("ROM PARSING TESTS")
    print("="*60)

    # Test basic parsing
    rom = parse_rom_filename("Super Mario Bros. (USA).zip")
    if rom.base_title == "Super Mario Bros." and rom.region == "USA":
        results.ok("Basic USA ROM parsing")
    else:
        results.fail("Basic USA ROM parsing",
                    "base_title='Super Mario Bros.', region='USA'",
                    f"base_title='{rom.base_title}', region='{rom.region}'")

    # Test revision detection
    rom = parse_rom_filename("Sonic the Hedgehog (USA) (Rev 1).zip")
    if rom.revision == 1:
        results.ok("Revision detection")
    else:
        results.fail("Revision detection", "revision=1", f"revision={rom.revision}")

    # Test beta detection
    rom = parse_rom_filename("Unreleased Game (USA) (Beta).zip")
    if rom.is_beta:
        results.ok("Beta detection")
    else:
        results.fail("Beta detection", "is_beta=True", f"is_beta={rom.is_beta}")

    # Test prototype detection
    rom = parse_rom_filename("Secret Game (USA) (Proto).zip")
    if rom.is_proto:
        results.ok("Prototype detection")
    else:
        results.fail("Prototype detection", "is_proto=True", f"is_proto={rom.is_proto}")

    # Test translation detection
    rom = parse_rom_filename("Final Fantasy V (Japan) [T-En by RPGe].zip")
    if rom.is_translation and rom.is_english:
        results.ok("Translation detection")
    else:
        results.fail("Translation detection",
                    "is_translation=True, is_english=True",
                    f"is_translation={rom.is_translation}, is_english={rom.is_english}")

    # Test re-release detection
    rom = parse_rom_filename("Zelda (USA) (Virtual Console).zip")
    if rom.is_rerelease:
        results.ok("Re-release detection (Virtual Console)")
    else:
        results.fail("Re-release detection", "is_rerelease=True", f"is_rerelease={rom.is_rerelease}")

    # Test compilation detection
    rom = parse_rom_filename("Sonic & Knuckles + Sonic the Hedgehog 3 (USA).zip")
    if rom.is_lock_on:
        results.ok("Lock-on detection")
    else:
        results.fail("Lock-on detection", "is_lock_on=True", f"is_lock_on={rom.is_lock_on}")

    # Test year extraction
    rom = parse_rom_filename("Game Title (USA) (1995).zip")
    if rom.year == 1995:
        results.ok("Year extraction")
    else:
        results.fail("Year extraction", "year=1995", f"year={rom.year}")

    # Test unlicensed detection
    rom = parse_rom_filename("Pirate Game (USA) (Unl).zip")
    if rom.is_unlicensed:
        results.ok("Unlicensed detection")
    else:
        results.fail("Unlicensed detection", "is_unlicensed=True", f"is_unlicensed={rom.is_unlicensed}")


def test_title_normalization():
    """Test title normalization and mappings."""
    print("\n" + "="*60)
    print("TITLE NORMALIZATION TESTS")
    print("="*60)

    # Test Rockman -> Mega Man mapping
    rom = parse_rom_filename("Rockman 2 - Dr. Wily no Nazo (Japan).zip")
    normalized = normalize_title(rom.base_title)
    if "mega man" in normalized:
        results.ok("Rockman -> Mega Man mapping")
    else:
        results.fail("Rockman -> Mega Man mapping",
                    "contains 'mega man'", f"'{normalized}'")

    # Test Pocket Monsters -> Pokemon mapping
    rom = parse_rom_filename("Pocket Monsters Aka (Japan).zip")
    normalized = normalize_title(rom.base_title)
    if "pokemon" in normalized and "red" in normalized:
        results.ok("Pocket Monsters -> Pokemon mapping")
    else:
        results.fail("Pocket Monsters -> Pokemon mapping",
                    "contains 'pokemon' and 'red'", f"'{normalized}'")

    # Test roman numeral conversion
    rom = parse_rom_filename("Final Fantasy III (USA).zip")
    normalized = normalize_title(rom.base_title)
    if "3" in normalized or "iii" in normalized.lower():
        results.ok("Roman numeral handling")
    else:
        results.fail("Roman numeral handling", "contains '3' or 'iii'", f"'{normalized}'")


def test_rom_selection():
    """Test ROM selection logic."""
    print("\n" + "="*60)
    print("ROM SELECTION TESTS")
    print("="*60)

    # Create test ROMs
    usa_rom = parse_rom_filename("Game (USA).zip")
    europe_rom = parse_rom_filename("Game (Europe).zip")
    japan_rom = parse_rom_filename("Game (Japan).zip")
    world_rom = parse_rom_filename("Game (World).zip")

    roms = [japan_rom, europe_rom, usa_rom]
    best = select_best_rom(roms)
    if best and best.region == "USA":
        results.ok("USA preferred over Europe/Japan")
    else:
        results.fail("USA preferred over Europe/Japan",
                    "region='USA'", f"region='{best.region if best else None}'")

    # Test World fallback
    roms = [japan_rom, world_rom]
    best = select_best_rom(roms)
    if best and best.region == "World":
        results.ok("World preferred over Japan-only")
    else:
        results.fail("World preferred over Japan-only",
                    "region='World'", f"region='{best.region if best else None}'")

    # Test revision preference
    rev0 = parse_rom_filename("Game (USA).zip")
    rev1 = parse_rom_filename("Game (USA) (Rev 1).zip")
    rev2 = parse_rom_filename("Game (USA) (Rev 2).zip")
    roms = [rev0, rev2, rev1]
    best = select_best_rom(roms)
    if best and best.revision == 2:
        results.ok("Latest revision preferred")
    else:
        results.fail("Latest revision preferred",
                    "revision=2", f"revision={best.revision if best else None}")

    # Test translation inclusion for Japan-only
    japan_only = parse_rom_filename("Japan Only Game (Japan).zip")
    translation = parse_rom_filename("Japan Only Game (Japan) [T-En by Translator].zip")
    roms = [japan_only, translation]
    best = select_best_rom(roms)
    if best and best.is_translation:
        results.ok("Translation preferred for Japan-only game")
    else:
        results.fail("Translation preferred for Japan-only game",
                    "is_translation=True", f"is_translation={best.is_translation if best else None}")

    # Test custom region priority - within English versions, should pick first in priority
    # Note: Japan-only (non-English) games are still lower priority than any English version
    usa_rom2 = parse_rom_filename("Game (USA).zip")
    europe_rom2 = parse_rom_filename("Game (Europe).zip")
    roms = [usa_rom2, europe_rom2]
    best = select_best_rom(roms, region_priority=["Europe", "USA"])
    if best and best.region == "Europe":
        results.ok("Custom region priority (Europe before USA)")
    else:
        results.fail("Custom region priority (Europe before USA)",
                    "region='Europe'", f"region='{best.region if best else None}'")


# =============================================================================
# Config File Tests
# =============================================================================

def test_config_handling():
    """Test config file loading and generation."""
    print("\n" + "="*60)
    print("CONFIG FILE TESTS")
    print("="*60)

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "retro-refiner.yaml"

        # Test config generation
        result = generate_default_config(config_path)
        if result and config_path.exists():
            results.ok("Config file generation")
        else:
            results.fail("Config file generation", "file created", "file not created")
            return

        # Test config loading
        if YAML_AVAILABLE:
            config = load_config(config_path)
            if isinstance(config, dict) and "region_priority" in config:
                results.ok("Config file loading (YAML)")
            else:
                results.fail("Config file loading (YAML)",
                            "dict with region_priority", f"{type(config)}")
        else:
            results.ok("Config loading skipped (PyYAML not installed)")

        # Test JSON config
        json_path = Path(tmpdir) / "config.json"
        with open(json_path, 'w') as f:
            json.dump({"region_priority": "Japan,USA", "flat": True}, f)

        config = load_config(json_path)
        if config.get("flat") == True:
            results.ok("JSON config loading")
        else:
            results.fail("JSON config loading", "flat=True", f"flat={config.get('flat')}")


# =============================================================================
# Network Source Tests
# =============================================================================

def test_url_functions():
    """Test URL handling functions."""
    print("\n" + "="*60)
    print("URL HANDLING TESTS")
    print("="*60)

    # Test is_url
    if is_url("https://example.com/roms/"):
        results.ok("is_url detects HTTPS")
    else:
        results.fail("is_url detects HTTPS", "True", "False")

    if is_url("http://example.com/roms/"):
        results.ok("is_url detects HTTP")
    else:
        results.fail("is_url detects HTTP", "True", "False")

    if not is_url("/local/path/to/roms"):
        results.ok("is_url rejects local path")
    else:
        results.fail("is_url rejects local path", "False", "True")

    # Test parse_url
    scheme, host, path = parse_url("https://example.com/roms/nes/")
    if scheme == "https" and host == "example.com" and path == "/roms/nes/":
        results.ok("parse_url components")
    else:
        results.fail("parse_url components",
                    "('https', 'example.com', '/roms/nes/')",
                    f"('{scheme}', '{host}', '{path}')")

    # Test normalize_url - relative path
    base = "https://example.com/roms/nes/"
    normalized = normalize_url("game.zip", base)
    if normalized == "https://example.com/roms/nes/game.zip":
        results.ok("normalize_url relative path")
    else:
        results.fail("normalize_url relative path",
                    "https://example.com/roms/nes/game.zip", normalized)

    # Test normalize_url - parent directory
    normalized = normalize_url("../snes/game.zip", base)
    if normalized == "https://example.com/roms/snes/game.zip":
        results.ok("normalize_url parent directory (../)")
    else:
        results.fail("normalize_url parent directory (../)",
                    "https://example.com/roms/snes/game.zip", normalized)

    # Test normalize_url - absolute path
    normalized = normalize_url("/other/path/game.zip", base)
    if normalized == "https://example.com/other/path/game.zip":
        results.ok("normalize_url absolute path")
    else:
        results.fail("normalize_url absolute path",
                    "https://example.com/other/path/game.zip", normalized)

    # Test normalize_url - skip different domain
    normalized = normalize_url("https://other.com/game.zip", base)
    if normalized is None:
        results.ok("normalize_url rejects different domain")
    else:
        results.fail("normalize_url rejects different domain", "None", normalized)

    # Test get_filename_from_url
    filename = get_filename_from_url("https://example.com/roms/Super%20Mario%20Bros.%20(USA).zip")
    if filename == "Super Mario Bros. (USA).zip":
        results.ok("get_filename_from_url with encoding")
    else:
        results.fail("get_filename_from_url with encoding",
                    "Super Mario Bros. (USA).zip", filename)


def test_html_parsing():
    """Test HTML directory listing parsing."""
    print("\n" + "="*60)
    print("HTML PARSING TESTS")
    print("="*60)

    base_url = "https://example.com/roms/nes/"

    # Test Apache-style autoindex
    apache_html = '''
    <html><body>
    <h1>Index of /roms/nes/</h1>
    <table>
    <tr><td><a href="../">Parent Directory</a></td></tr>
    <tr><td><a href="Super%20Mario%20Bros.%20(USA).zip">Super Mario Bros. (USA).zip</a></td></tr>
    <tr><td><a href="Zelda%20(USA).zip">Zelda (USA).zip</a></td></tr>
    <tr><td><a href="usa/">usa/</a></td></tr>
    </table>
    </body></html>
    '''

    files = parse_html_for_files(apache_html, base_url)
    if len(files) == 2 and any("Mario" in f for f in files):
        results.ok("Apache autoindex file extraction")
    else:
        results.fail("Apache autoindex file extraction", "2 files with Mario", f"{len(files)} files")

    dirs = parse_html_for_directories(apache_html, base_url)
    if len(dirs) == 1 and "usa/" in dirs[0]:
        results.ok("Apache autoindex directory extraction")
    else:
        results.fail("Apache autoindex directory extraction", "1 dir (usa/)", f"{len(dirs)} dirs")

    # Test nginx-style
    nginx_html = '''
    <html><head><title>Index of /roms/</title></head>
    <body><h1>Index of /roms/</h1><hr><pre>
    <a href="../">../</a>
    <a href="nes/">nes/</a>
    <a href="snes/">snes/</a>
    <a href="genesis/">genesis/</a>
    </pre></body></html>
    '''

    dirs = parse_html_for_directories(nginx_html, "https://example.com/roms/")
    if len(dirs) >= 3:
        results.ok("nginx directory listing")
    else:
        results.fail("nginx directory listing", ">=3 dirs", f"{len(dirs)} dirs")

    # Test custom HTML with various link formats
    custom_html = '''
    <html><body>
    <div class="file-list">
        <a href="game1.zip">Game 1</a>
        <a data-url="game2.zip">Game 2</a>
        <span data-href="game3.zip">Game 3</span>
    </div>
    <pre>
    game4.zip  1024  2024-01-01
    game5.7z   2048  2024-01-02
    </pre>
    </body></html>
    '''

    links = extract_links_from_html(custom_html)
    # Should find href, data-url, data-href patterns
    if len(links) >= 3:
        results.ok("Multiple link format extraction")
    else:
        results.fail("Multiple link format extraction", ">=3 links", f"{len(links)} links")

    # Test ROM file detection
    if is_rom_file("game.zip") and is_rom_file("game.7z") and is_rom_file("game.nes"):
        results.ok("ROM file extension detection")
    else:
        results.fail("ROM file extension detection", "True for .zip/.7z/.nes", "False")

    if not is_rom_file("readme.txt") and not is_rom_file("image.png"):
        results.ok("Non-ROM file rejection")
    else:
        results.fail("Non-ROM file rejection", "False for .txt/.png", "True")

    # Test directory link detection
    if is_directory_link("games/") and is_directory_link("nes/"):
        results.ok("Directory link detection (trailing /)")
    else:
        results.fail("Directory link detection", "True for trailing /", "False")


# =============================================================================
# Filter Tests
# =============================================================================

def test_pattern_matching():
    """Test include/exclude pattern matching."""
    print("\n" + "="*60)
    print("PATTERN MATCHING TESTS")
    print("="*60)

    # Test glob patterns
    if matches_patterns("Super Mario Bros. (USA).zip", ["*Mario*"]):
        results.ok("Glob pattern *Mario* matches")
    else:
        results.fail("Glob pattern match", "True", "False")

    if not matches_patterns("Sonic (USA).zip", ["*Mario*"]):
        results.ok("Glob pattern *Mario* doesn't match Sonic")
    else:
        results.fail("Glob pattern non-match", "False", "True")

    # Test multiple patterns (OR logic)
    if matches_patterns("Zelda (USA).zip", ["*Mario*", "*Zelda*"]):
        results.ok("Multiple patterns (OR logic)")
    else:
        results.fail("Multiple patterns (OR logic)", "True", "False")

    # Test case insensitivity
    if matches_patterns("SUPER MARIO BROS.zip", ["*mario*"]):
        results.ok("Case insensitive matching")
    else:
        results.fail("Case insensitive matching", "True", "False")


def test_network_rom_filtering():
    """Test network ROM URL filtering."""
    print("\n" + "="*60)
    print("NETWORK ROM FILTERING TESTS")
    print("="*60)

    test_urls = [
        "https://example.com/nes/Super Mario Bros. (USA).zip",
        "https://example.com/nes/Super Mario Bros. (Japan).zip",
        "https://example.com/nes/Super Mario Bros. 2 (USA).zip",
        "https://example.com/nes/Zelda (USA).zip",
        "https://example.com/nes/Beta Game (USA) (Beta).zip",
        "https://example.com/nes/Proto Game (USA) (Proto).zip",
        "https://example.com/nes/Pirate Game (USA) (Unl).zip",
    ]

    # Test include pattern filtering
    filtered = filter_network_roms(
        test_urls, "nes",
        include_patterns=["*Mario*"],
        region_priority=DEFAULT_REGION_PRIORITY
    )
    mario_count = sum(1 for u in filtered if "Mario" in u)
    if mario_count >= 1 and not any("Zelda" in u for u in filtered):
        results.ok("Include pattern filtering (Mario only)")
    else:
        results.fail("Include pattern filtering", "Mario only, no Zelda",
                    f"{mario_count} Mario, Zelda present: {any('Zelda' in u for u in filtered)}")

    # Test beta exclusion (default)
    filtered = filter_network_roms(
        test_urls, "nes",
        include_betas=False,
        region_priority=DEFAULT_REGION_PRIORITY
    )
    if not any("Beta" in u for u in filtered):
        results.ok("Beta ROM exclusion (default)")
    else:
        results.fail("Beta ROM exclusion", "no Beta", "Beta found")

    # Test proto inclusion - proto passes through filter
    # Note: filter_network_roms calls select_best_rom which also filters,
    # but protos are kept by select_best_rom (unlike betas)
    proto_urls = [
        "https://example.com/nes/Proto Game (USA) (Proto).zip",
    ]
    filtered = filter_network_roms(
        proto_urls, "nes",
        include_protos=True,
        region_priority=DEFAULT_REGION_PRIORITY
    )
    if len(filtered) == 1:
        results.ok("Proto ROM inclusion (--include-protos)")
    else:
        results.fail("Proto ROM inclusion", "1 ROM", f"{len(filtered)} ROMs")

    # Test region selection (USA preferred)
    filtered = filter_network_roms(
        test_urls, "nes",
        region_priority=["USA", "Japan"],
        include_patterns=["*Mario Bros.*"]  # Match both USA and Japan versions
    )
    # Should select USA version for "Super Mario Bros." group
    usa_selected = any("(USA)" in u and "Super Mario Bros." in u and "2" not in u for u in filtered)
    if usa_selected:
        results.ok("Region priority (USA selected over Japan)")
    else:
        results.fail("Region priority", "USA version selected", f"Selected: {filtered}")


# =============================================================================
# System Detection Tests
# =============================================================================

def test_system_detection():
    """Test system detection from folders and extensions."""
    print("\n" + "="*60)
    print("SYSTEM DETECTION TESTS")
    print("="*60)

    # Test folder aliases
    if FOLDER_ALIASES.get("megadrive") == "genesis":
        results.ok("Folder alias: megadrive -> genesis")
    else:
        results.fail("Folder alias", "genesis", FOLDER_ALIASES.get("megadrive"))

    if FOLDER_ALIASES.get("famicom") == "nes":
        results.ok("Folder alias: famicom -> nes")
    else:
        results.fail("Folder alias", "nes", FOLDER_ALIASES.get("famicom"))

    # Test extension mapping
    if EXTENSION_TO_SYSTEM.get(".nes") == "nes":
        results.ok("Extension mapping: .nes -> nes")
    else:
        results.fail("Extension mapping", "nes", EXTENSION_TO_SYSTEM.get(".nes"))

    if EXTENSION_TO_SYSTEM.get(".sfc") == "snes":
        results.ok("Extension mapping: .sfc -> snes")
    else:
        results.fail("Extension mapping", "snes", EXTENSION_TO_SYSTEM.get(".sfc"))

    if EXTENSION_TO_SYSTEM.get(".md") == "genesis":
        results.ok("Extension mapping: .md -> genesis")
    else:
        results.fail("Extension mapping", "genesis", EXTENSION_TO_SYSTEM.get(".md"))

    # Test known systems
    if "nes" in KNOWN_SYSTEMS and "snes" in KNOWN_SYSTEMS and "mame" in KNOWN_SYSTEMS:
        results.ok("Known systems include nes, snes, mame")
    else:
        results.fail("Known systems", "contains nes, snes, mame", str(KNOWN_SYSTEMS[:10]))


# =============================================================================
# Playlist Generation Tests
# =============================================================================

def test_playlist_generation():
    """Test playlist generation functions."""
    print("\n" + "="*60)
    print("PLAYLIST GENERATION TESTS")
    print("="*60)

    with tempfile.TemporaryDirectory() as tmpdir:
        dest_path = Path(tmpdir)

        # Create mock ROM files
        rom_files = [
            dest_path / "Game A (USA).zip",
            dest_path / "Game B (USA).zip",
            dest_path / "Game C (Japan).zip",
        ]
        for f in rom_files:
            f.touch()

        # Test M3U generation
        generate_m3u_playlist("nes", rom_files, dest_path)
        m3u_path = dest_path / "nes.m3u"
        if m3u_path.exists():
            content = m3u_path.read_text()
            if "Game A" in content and "Game B" in content:
                results.ok("M3U playlist generation")
            else:
                results.fail("M3U playlist content", "contains game names", content[:100])
        else:
            results.fail("M3U playlist generation", "file created", "file not found")

        # Test gamelist.xml generation
        generate_gamelist_xml("nes", rom_files, dest_path)
        xml_path = dest_path / "gamelist.xml"
        if xml_path.exists():
            content = xml_path.read_text()
            if "<gameList>" in content and "<game>" in content:
                results.ok("gamelist.xml generation")
            else:
                results.fail("gamelist.xml content", "valid XML structure", content[:100])
        else:
            results.fail("gamelist.xml generation", "file created", "file not found")


# =============================================================================
# Integration Tests (with real files if available)
# =============================================================================

def test_real_roms(source_dir: str):
    """Test with real ROM files if available."""
    source_path = Path(source_dir)

    if not source_path.exists():
        print("\n" + "="*60)
        print("INTEGRATION TESTS (SKIPPED - source not found)")
        print("="*60)
        return

    print("\n" + "="*60)
    print("INTEGRATION TESTS (with real ROMs)")
    print("="*60)

    # Find a system with ROMs
    test_system = None
    for system in ["nes", "snes", "genesis", "gba", "vectrex"]:
        system_path = source_path / system
        if system_path.exists() and any(system_path.iterdir()):
            test_system = system
            break

    if not test_system:
        print("  No ROM directories found, skipping integration tests")
        return

    system_path = source_path / test_system
    rom_files = list(system_path.glob("*.zip"))[:10]  # Test with up to 10 ROMs

    if rom_files:
        # Parse all ROMs
        parsed = [parse_rom_filename(f.name) for f in rom_files]

        # Group by title
        grouped = defaultdict(list)
        for rom in parsed:
            normalized = normalize_title(rom.base_title)
            grouped[normalized].append(rom)

        # Select best from a group
        # Note: Many games may return None if they're unlicensed, pirate, beta, etc.
        tested = 0
        for title, roms in list(grouped.items()):
            if tested >= 3:
                break
            best = select_best_rom(roms)
            if best:
                results.ok(f"Selection for '{title[:30]}...' -> {best.region}")
                tested += 1
            # Skip failures - many legitimate reasons for None (unlicensed, pirate, etc.)


def test_series(source_dir: str, system: str, search_term: str):
    """Test ROM selection for a specific series (legacy function)."""
    source_path = Path(source_dir) / system

    if not source_path.exists():
        print(f"Directory not found: {source_path}")
        return

    # Find matching ROMs
    matching_roms = []
    for filename in os.listdir(source_path):
        if search_term.lower() in filename.lower():
            rom_info = parse_rom_filename(filename)
            matching_roms.append(rom_info)

    if not matching_roms:
        print(f"No ROMs found matching '{search_term}' in {system}")
        return

    print(f"\n{'='*80}")
    print(f"TESTING: '{search_term}' in {system.upper()}")
    print(f"{'='*80}")
    print(f"Found {len(matching_roms)} matching ROMs\n")

    # Group by normalized title
    grouped = defaultdict(list)
    for rom in matching_roms:
        normalized = normalize_title(rom.base_title)
        grouped[normalized].append(rom)

    print(f"Grouped into {len(grouped)} unique games:\n")

    for title, roms in sorted(grouped.items()):
        print(f"\n--- {title} ({len(roms)} ROMs) ---")

        # Show all ROMs in this group
        for rom in sorted(roms, key=lambda r: r.filename):
            flags = []
            if rom.is_beta: flags.append("BETA")
            if rom.is_proto: flags.append("PROTO")
            if rom.is_demo: flags.append("DEMO")
            if rom.is_promo: flags.append("PROMO")
            if rom.is_sample: flags.append("SAMPLE")
            if rom.is_rerelease: flags.append("RERELEASE")
            if rom.is_pirate: flags.append("PIRATE")
            if rom.is_translation: flags.append("TRANSLATION")
            if rom.is_compilation: flags.append("COMPILATION")
            if rom.is_lock_on: flags.append("LOCK-ON")
            if rom.is_bios: flags.append("BIOS")
            if rom.has_hacks: flags.append("HACKED")
            if not rom.is_english: flags.append("NON-EN")

            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"  {rom.filename}")
            print(f"    Region: {rom.region}, Rev: {rom.revision}, English: {rom.is_english}{flag_str}")

        # Show selected ROM
        best = select_best_rom(roms)
        if best:
            print(f"\n  >>> SELECTED: {best.filename}")
        else:
            print(f"\n  >>> NO ROM SELECTED (all filtered out)")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("RETRO-REFINER TEST SUITE")
    print("="*60)

    # Run unit tests
    test_rom_parsing()
    test_title_normalization()
    test_rom_selection()
    test_config_handling()
    test_url_functions()
    test_html_parsing()
    test_pattern_matching()
    test_network_rom_filtering()
    test_system_detection()
    test_playlist_generation()

    # Run integration tests with real files
    source = r"C:\Users\atkin\Downloads\Roms"
    test_real_roms(source)

    # Print summary
    success = results.summary()

    # Optional: Run legacy series tests
    if "--series" in sys.argv and Path(source).exists():
        print("\n" + "="*60)
        print("SERIES SELECTION TESTS")
        print("="*60)
        test_series(source, "genesis", "golden axe")
        test_series(source, "snes", "final fantasy")
        test_series(source, "snes", "super mario world")
        test_series(source, "n64", "zelda")
        test_series(source, "genesis", "sonic the hedgehog")
        test_series(source, "nes", "super mario bros")

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
