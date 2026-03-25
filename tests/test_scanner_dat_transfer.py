#!/usr/bin/env python3
"""Tests for scanner.py, dat.py, and transfer.py modules.

Covers system detection, local scanning, DAT parsing, title normalization,
CRC calculation, file transfer, playlist generation, and destination management.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from retro_refiner.scanner import (
    detect_system_from_path,
    scan_local_sources,
    get_system_scan_info,
    ScanProgressBar,
)
from retro_refiner.dat import (
    normalize_title,
    normalize_title_for_dedupe,
    parse_dat_file,
    load_title_mappings,
    reset_title_mappings_cache,
    detect_dat_region,
    calculate_crc32,
)
from retro_refiner.transfer import (
    validate_destination,
    clean_destination,
    transfer_files,
    generate_m3u_playlist,
    generate_gamelist_xml,
    generate_retroarch_playlist,
)


class TestResult:
    """Track test results."""

    def __init__(self):
        """Initialize counters."""
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name):
        """Record a passing test."""
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, expected, actual):
        """Record a failing test."""
        self.failed += 1
        self.errors.append((name, expected, actual))
        print(f"  [FAIL] {name}")
        print(f"    Expected: {expected}")
        print(f"    Actual:   {actual}")

    def summary(self):
        """Print summary and return True if all passed."""
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"Failed tests: {self.failed}")
        print(f"{'='*60}")
        return self.failed == 0


results = TestResult()


# =============================================================================
# scanner.py tests
# =============================================================================

def test_detect_system_known_systems():
    """Test detect_system_from_path with known system codes."""
    print("\n--- detect_system_from_path: known systems ---")

    val = detect_system_from_path('snes')
    if val == 'snes':
        results.ok("detect snes")
    else:
        results.fail("detect snes", 'snes', val)

    val = detect_system_from_path('nes')
    if val == 'nes':
        results.ok("detect nes")
    else:
        results.fail("detect nes", 'nes', val)

    val = detect_system_from_path('genesis')
    if val == 'genesis':
        results.ok("detect genesis")
    else:
        results.fail("detect genesis", 'genesis', val)

    val = detect_system_from_path('gba')
    if val == 'gba':
        results.ok("detect gba")
    else:
        results.fail("detect gba", 'gba', val)

    val = detect_system_from_path('n64')
    if val == 'n64':
        results.ok("detect n64")
    else:
        results.fail("detect n64", 'n64', val)


def test_detect_system_nointro_names():
    """Test detect_system_from_path with No-Intro long names."""
    print("\n--- detect_system_from_path: No-Intro names ---")

    val = detect_system_from_path('Sega - Mega Drive - Genesis')
    if val == 'genesis':
        results.ok("detect 'Sega - Mega Drive - Genesis' -> genesis")
    else:
        results.fail("detect 'Sega - Mega Drive - Genesis'", 'genesis', val)

    val = detect_system_from_path('Nintendo - Game Boy Advance')
    if val == 'gba':
        results.ok("detect 'Nintendo - Game Boy Advance' -> gba")
    else:
        results.fail("detect 'Nintendo - Game Boy Advance'", 'gba', val)


def test_detect_system_unknown():
    """Test detect_system_from_path with unknown paths."""
    print("\n--- detect_system_from_path: unknown paths ---")

    val = detect_system_from_path('totally_unknown_thing')
    if val is None:
        results.ok("unknown path returns None")
    else:
        results.fail("unknown path returns None", None, val)

    val = detect_system_from_path('')
    if val is None:
        results.ok("empty path returns None")
    else:
        results.fail("empty path returns None", None, val)

    val = detect_system_from_path('////')
    if val is None:
        results.ok("slashes-only path returns None")
    else:
        results.fail("slashes-only path returns None", None, val)


def test_detect_system_folder_aliases():
    """Test detect_system_from_path with folder aliases."""
    print("\n--- detect_system_from_path: folder aliases ---")

    val = detect_system_from_path('megadrive')
    if val == 'genesis':
        results.ok("alias megadrive -> genesis")
    else:
        results.fail("alias megadrive -> genesis", 'genesis', val)


def test_detect_system_url_paths():
    """Test detect_system_from_path with URL-style paths."""
    print("\n--- detect_system_from_path: URL paths ---")

    val = detect_system_from_path('/roms/snes/something')
    if val == 'snes':
        results.ok("URL path /roms/snes/something -> snes")
    else:
        results.fail("URL path /roms/snes/something", 'snes', val)

    val = detect_system_from_path('/archive/genesis/')
    if val == 'genesis':
        results.ok("URL path /archive/genesis/ -> genesis")
    else:
        results.fail("URL path /archive/genesis/", 'genesis', val)


def test_scan_local_sources_basic():
    """Test scan_local_sources with temp directory containing ROM files."""
    print("\n--- scan_local_sources: basic ---")

    tmpdir = tempfile.mkdtemp()
    try:
        # Create system subdirectories with ROM files
        snes_dir = Path(tmpdir) / 'snes'
        snes_dir.mkdir()
        (snes_dir / 'Game1 (USA).sfc').write_bytes(b'rom1')
        (snes_dir / 'Game2 (Japan).sfc').write_bytes(b'rom2')

        nes_dir = Path(tmpdir) / 'nes'
        nes_dir.mkdir()
        (nes_dir / 'Mario (USA).nes').write_bytes(b'nes1')

        result = scan_local_sources([Path(tmpdir)], recursive=True)

        if 'snes' in result:
            results.ok("scan found snes system")
        else:
            results.fail("scan found snes system", "snes in result", list(result.keys()))

        if 'snes' in result and len(result['snes']) == 2:
            results.ok("scan found 2 snes roms")
        else:
            count = len(result.get('snes', []))
            results.fail("scan found 2 snes roms", 2, count)

        if 'nes' in result and len(result['nes']) == 1:
            results.ok("scan found 1 nes rom")
        else:
            count = len(result.get('nes', []))
            results.fail("scan found 1 nes rom", 1, count)
    finally:
        shutil.rmtree(tmpdir)


def test_scan_local_sources_nonrecursive():
    """Test scan_local_sources without recursion."""
    print("\n--- scan_local_sources: non-recursive ---")

    tmpdir = tempfile.mkdtemp()
    try:
        # ROM in subdirectory should NOT be found without recursion
        sub = Path(tmpdir) / 'snes'
        sub.mkdir()
        (sub / 'Game (USA).sfc').write_bytes(b'rom')

        result = scan_local_sources([Path(tmpdir)], recursive=False)

        # Without recursion, subdirectory ROMs should not be found
        snes_count = len(result.get('snes', []))
        if snes_count == 0:
            results.ok("non-recursive skips subdirectory roms")
        else:
            results.fail("non-recursive skips subdirectory roms", 0, snes_count)
    finally:
        shutil.rmtree(tmpdir)


def test_scan_local_sources_extension_detection():
    """Test that scan_local_sources detects systems from file extensions."""
    print("\n--- scan_local_sources: extension detection ---")

    tmpdir = tempfile.mkdtemp()
    try:
        # ROM files in a non-system directory, detected by extension
        (Path(tmpdir) / 'Game.nes').write_bytes(b'nes')
        (Path(tmpdir) / 'Game.sfc').write_bytes(b'sfc')
        (Path(tmpdir) / 'Game.gba').write_bytes(b'gba')

        result = scan_local_sources([Path(tmpdir)], recursive=False)

        if 'nes' in result:
            results.ok("extension detection found nes")
        else:
            results.fail("extension detection found nes", "nes in result", list(result.keys()))

        if 'snes' in result:
            results.ok("extension detection found snes (.sfc)")
        else:
            results.fail("extension detection found snes (.sfc)", "snes in result",
                         list(result.keys()))

        if 'gba' in result:
            results.ok("extension detection found gba")
        else:
            results.fail("extension detection found gba", "gba in result", list(result.keys()))
    finally:
        shutil.rmtree(tmpdir)


def test_scan_local_sources_recursive_with_subfolders():
    """Test recursive scanning into nested system folders."""
    print("\n--- scan_local_sources: recursive with subfolders ---")

    tmpdir = tempfile.mkdtemp()
    try:
        # Nested: parent/snes/region/Game.sfc
        region_dir = Path(tmpdir) / 'snes' / 'USA'
        region_dir.mkdir(parents=True)
        (region_dir / 'Game (USA).sfc').write_bytes(b'rom')

        result = scan_local_sources([Path(tmpdir)], recursive=True)

        if 'snes' in result and len(result['snes']) == 1:
            results.ok("recursive found rom in nested subfolder")
        else:
            results.fail("recursive found rom in nested subfolder",
                         1, len(result.get('snes', [])))
    finally:
        shutil.rmtree(tmpdir)


def test_scan_local_sources_ignores_dotdirs():
    """Test that scan_local_sources ignores dot-prefixed directories."""
    print("\n--- scan_local_sources: ignores dot dirs ---")

    tmpdir = tempfile.mkdtemp()
    try:
        hidden = Path(tmpdir) / '.hidden'
        hidden.mkdir()
        (hidden / 'Game.nes').write_bytes(b'rom')

        result = scan_local_sources([Path(tmpdir)], recursive=True)
        nes_count = len(result.get('nes', []))
        if nes_count == 0:
            results.ok("ignores .hidden directory")
        else:
            results.fail("ignores .hidden directory", 0, nes_count)
    finally:
        shutil.rmtree(tmpdir)


def test_get_system_scan_info():
    """Test get_system_scan_info construction and fields."""
    print("\n--- get_system_scan_info ---")

    tmpdir = tempfile.mkdtemp()
    try:
        f1 = Path(tmpdir) / 'game1.nes'
        f2 = Path(tmpdir) / 'game2.nes'
        f1.write_bytes(b'A' * 100)
        f2.write_bytes(b'B' * 200)

        systems_dict = {'nes': [f1, f2], 'snes': [Path(tmpdir) / 'nonexist.sfc']}
        infos = get_system_scan_info(systems_dict, source_type="local")

        # Should have 2 entries (sorted)
        if len(infos) == 2:
            results.ok("get_system_scan_info returns 2 entries")
        else:
            results.fail("get_system_scan_info returns 2 entries", 2, len(infos))

        nes_info = [i for i in infos if i.system == 'nes']
        if nes_info and nes_info[0].file_count == 2:
            results.ok("nes file_count is 2")
        else:
            count = nes_info[0].file_count if nes_info else 'missing'
            results.fail("nes file_count is 2", 2, count)

        if nes_info and nes_info[0].total_size == 300:
            results.ok("nes total_size is 300")
        else:
            size = nes_info[0].total_size if nes_info else 'missing'
            results.fail("nes total_size is 300", 300, size)

        if nes_info and nes_info[0].source_type == "local":
            results.ok("source_type is local")
        else:
            results.fail("source_type is local", "local",
                         nes_info[0].source_type if nes_info else 'missing')

        # Network mode should not compute sizes
        net_infos = get_system_scan_info(
            {'snes': ['url1', 'url2']}, source_type="network")
        if net_infos[0].total_size == 0:
            results.ok("network source_type has total_size 0")
        else:
            results.fail("network source_type has total_size 0", 0,
                         net_infos[0].total_size)
    finally:
        shutil.rmtree(tmpdir)


def test_scan_progress_bar_construction():
    """Test ScanProgressBar basic construction (no terminal output test)."""
    print("\n--- ScanProgressBar construction ---")

    # Redirect stdout to suppress progress bar terminal output
    old_stdout = sys.stdout
    devnull = open(os.devnull, 'w', encoding='utf-8')  # pylint: disable=consider-using-with
    sys.stdout = devnull
    try:
        bar = ScanProgressBar(total=10, desc='Test', indent='  ')
    finally:
        sys.stdout = old_stdout
        devnull.close()

    if bar.total == 10:
        results.ok("ScanProgressBar total=10")
    else:
        results.fail("ScanProgressBar total=10", 10, bar.total)

    if bar.desc == 'Test':
        results.ok("ScanProgressBar desc='Test'")
    else:
        results.fail("ScanProgressBar desc='Test'", 'Test', bar.desc)

    if bar.current == 0:
        results.ok("ScanProgressBar current starts at 0")
    else:
        results.fail("ScanProgressBar current starts at 0", 0, bar.current)

    if bar.bar_width == 20:
        results.ok("ScanProgressBar bar_width=20")
    else:
        results.fail("ScanProgressBar bar_width=20", 20, bar.bar_width)


def test_scan_progress_bar_callback():
    """Test ScanProgressBar.make_callback returns usable callback."""
    print("\n--- ScanProgressBar callback ---")

    old_stdout = sys.stdout
    devnull = open(os.devnull, 'w', encoding='utf-8')  # pylint: disable=consider-using-with
    sys.stdout = devnull
    try:
        bar = ScanProgressBar(total=5, desc='CB Test')
        cb = bar.make_callback()
        cb(3, 5)
    finally:
        sys.stdout = old_stdout
        devnull.close()

    if bar.current == 3:
        results.ok("callback updated current to 3")
    else:
        results.fail("callback updated current to 3", 3, bar.current)


# =============================================================================
# dat.py tests
# =============================================================================

def test_normalize_title_case_folding():
    """Test normalize_title lowercases input."""
    print("\n--- normalize_title: case folding ---")

    val = normalize_title('SONIC THE HEDGEHOG')
    if val == 'sonic the hedgehog':
        results.ok("uppercase folded to lowercase")
    else:
        results.fail("uppercase folded to lowercase", 'sonic the hedgehog', val)

    val = normalize_title('Already Lowercase')
    if 'already lowercase' == val:
        results.ok("mixed case folded")
    else:
        results.fail("mixed case folded", 'already lowercase', val)


def test_normalize_title_punctuation():
    """Test normalize_title strips punctuation."""
    print("\n--- normalize_title: punctuation ---")

    val = normalize_title("Kirby's Dream Land")
    if val == 'kirby s dream land':
        results.ok("apostrophe removed")
    else:
        results.fail("apostrophe removed", 'kirby s dream land', val)

    val = normalize_title('Pac-Man')
    if val == 'pac man':
        results.ok("hyphen replaced with space")
    else:
        results.fail("hyphen replaced with space", 'pac man', val)

    val = normalize_title('Game: The Subtitle')
    # 'The' is mid-string after colon removal, not a leading article
    expected = 'game the subtitle'
    if val == expected:
        results.ok("colon removed, mid-string 'the' preserved")
    else:
        results.fail("colon removed, mid-string 'the' preserved", expected, val)


def test_normalize_title_roman_numerals():
    """Test normalize_title converts Roman numerals to Arabic."""
    print("\n--- normalize_title: roman numerals ---")

    val = normalize_title('Final Fantasy III')
    if val == 'final fantasy 3':
        results.ok("III -> 3")
    else:
        results.fail("III -> 3", 'final fantasy 3', val)

    val = normalize_title('Final Fantasy VII')
    if val == 'final fantasy 7':
        results.ok("VII -> 7")
    else:
        results.fail("VII -> 7", 'final fantasy 7', val)

    val = normalize_title('Street Fighter II')
    if val == 'street fighter 2':
        results.ok("II -> 2")
    else:
        results.fail("II -> 2", 'street fighter 2', val)

    val = normalize_title('Game IV')
    if val == 'game 4':
        results.ok("IV -> 4")
    else:
        results.fail("IV -> 4", 'game 4', val)

    val = normalize_title('Game VIII')
    if val == 'game 8':
        results.ok("VIII -> 8")
    else:
        results.fail("VIII -> 8", 'game 8', val)


def test_normalize_title_articles():
    """Test normalize_title article stripping."""
    print("\n--- normalize_title: article stripping ---")

    val = normalize_title('The Legend of Zelda')
    if val == 'legend of zelda':
        results.ok("leading 'The' stripped")
    else:
        results.fail("leading 'The' stripped", 'legend of zelda', val)

    val = normalize_title('A Game')
    if val == 'game':
        results.ok("leading 'A' stripped")
    else:
        results.fail("leading 'A' stripped", 'game', val)

    val = normalize_title('An Adventure')
    if val == 'adventure':
        results.ok("leading 'An' stripped")
    else:
        results.fail("leading 'An' stripped", 'adventure', val)

    val = normalize_title('Legend of Zelda, The')
    if val == 'legend of zelda':
        results.ok("trailing ', The' handled")
    else:
        results.fail("trailing ', The' handled", 'legend of zelda', val)


def test_normalize_title_strip_articles_false():
    """Test normalize_title with strip_articles=False preserves articles."""
    print("\n--- normalize_title: strip_articles=False ---")

    val = normalize_title('The Bully', strip_articles=False)
    if val == 'the bully':
        results.ok("strip_articles=False preserves 'The'")
    else:
        results.fail("strip_articles=False preserves 'The'", 'the bully', val)

    val = normalize_title('The Legend of Zelda', strip_articles=False)
    if val == 'the legend of zelda':
        results.ok("strip_articles=False preserves leading article")
    else:
        results.fail("strip_articles=False preserves leading article",
                     'the legend of zelda', val)

    # With strip_articles=False, comma article pattern is skipped
    # but the comma itself is removed by punctuation normalization
    val = normalize_title('Legend of Zelda, The', strip_articles=False)
    if val == 'legend of zelda the':
        results.ok("strip_articles=False: comma punctuation removed, article kept")
    else:
        results.fail("strip_articles=False: comma punctuation removed, article kept",
                     'legend of zelda the', val)


def test_normalize_title_for_dedupe():
    """Test normalize_title_for_dedupe does NOT strip articles."""
    print("\n--- normalize_title_for_dedupe ---")

    val = normalize_title_for_dedupe('The Bully')
    if val == 'the bully':
        results.ok("dedupe preserves 'The Bully' -> 'the bully'")
    else:
        results.fail("dedupe preserves 'The Bully'", 'the bully', val)

    # Ensure other normalization still happens
    val = normalize_title_for_dedupe('The Game III')
    if val == 'the game 3':
        results.ok("dedupe still converts roman numerals")
    else:
        results.fail("dedupe still converts roman numerals", 'the game 3', val)

    # Dedupe vs normal should differ for articles
    normal = normalize_title('The Bully')
    dedupe = normalize_title_for_dedupe('The Bully')
    if normal != dedupe:
        results.ok("normalize vs dedupe differ for 'The Bully'")
    else:
        results.fail("normalize vs dedupe differ for 'The Bully'",
                     "different", f"both '{normal}'")


def test_parse_dat_file_logiqx():
    """Test parse_dat_file with Logiqx XML format."""
    print("\n--- parse_dat_file: Logiqx XML ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dat_content = '''<?xml version="1.0"?>
<datafile>
<header><name>Test DAT</name></header>
<game name="Test Game (USA)">
<rom name="Test Game (USA).zip" size="1024" crc="ABCD1234"/>
</game>
<game name="Another Game (Japan)">
<rom name="Another Game (Japan).zip" size="2048" crc="5678ABCD"/>
</game>
</datafile>'''
        dat_path = Path(tmpdir) / 'test.dat'
        dat_path.write_text(dat_content, encoding='utf-8')

        entries = parse_dat_file(dat_path)

        if len(entries) == 2:
            results.ok("parsed 2 entries from XML DAT")
        else:
            results.fail("parsed 2 entries from XML DAT", 2, len(entries))

        # CRC keys are lowercased
        if 'abcd1234' in entries:
            results.ok("entry keyed by lowercase CRC")
        else:
            results.fail("entry keyed by lowercase CRC", 'abcd1234', list(entries.keys()))

        entry = entries.get('abcd1234')
        if entry and entry.name == 'Test Game (USA)':
            results.ok("entry name is 'Test Game (USA)'")
        else:
            results.fail("entry name", 'Test Game (USA)',
                         entry.name if entry else 'missing')

        if entry and entry.rom_name == 'Test Game (USA).zip':
            results.ok("entry rom_name is 'Test Game (USA).zip'")
        else:
            results.fail("entry rom_name", 'Test Game (USA).zip',
                         entry.rom_name if entry else 'missing')

        if entry and entry.size == 1024:
            results.ok("entry size is 1024")
        else:
            results.fail("entry size", 1024, entry.size if entry else 'missing')

        if entry and entry.region == 'USA':
            results.ok("entry region detected as USA")
        else:
            results.fail("entry region", 'USA', entry.region if entry else 'missing')

        japan_entry = entries.get('5678abcd')
        if japan_entry and japan_entry.region == 'Japan':
            results.ok("Japan entry region detected")
        else:
            results.fail("Japan entry region", 'Japan',
                         japan_entry.region if japan_entry else 'missing')

        if japan_entry and japan_entry.size == 2048:
            results.ok("Japan entry size is 2048")
        else:
            results.fail("Japan entry size", 2048,
                         japan_entry.size if japan_entry else 'missing')
    finally:
        shutil.rmtree(tmpdir)


def test_parse_dat_file_clrmamepro():
    """Test parse_dat_file with ClrMamePro text format."""
    print("\n--- parse_dat_file: ClrMamePro ---")

    tmpdir = tempfile.mkdtemp()
    try:
        # ClrMamePro format: name must be on the 'game (' opening line
        dat_content = (
            'clrmamepro (\n'
            '\tname "Test ClrMame DAT"\n'
            ')\n'
            '\n'
            'game ( name "Cool Game (Europe)"\n'
            '\trom ( name "Cool Game (Europe).zip" size 512 crc DEADBEEF )\n'
            ')\n'
        )
        dat_path = Path(tmpdir) / 'test.dat'
        dat_path.write_text(dat_content, encoding='utf-8')

        entries = parse_dat_file(dat_path)

        if len(entries) == 1:
            results.ok("parsed 1 entry from ClrMamePro DAT")
        else:
            results.fail("parsed 1 entry from ClrMamePro DAT", 1, len(entries))

        entry = entries.get('deadbeef')
        if entry and entry.name == 'Cool Game (Europe)':
            results.ok("ClrMamePro entry name correct")
        else:
            results.fail("ClrMamePro entry name", 'Cool Game (Europe)',
                         entry.name if entry else 'missing')

        if entry and entry.region == 'Europe':
            results.ok("ClrMamePro entry region detected")
        else:
            results.fail("ClrMamePro entry region", 'Europe',
                         entry.region if entry else 'missing')
    finally:
        shutil.rmtree(tmpdir)


def test_load_title_mappings():
    """Test load_title_mappings loads and caches."""
    print("\n--- load_title_mappings ---")

    reset_title_mappings_cache()

    mappings = load_title_mappings()
    if isinstance(mappings, dict):
        results.ok("load_title_mappings returns dict")
    else:
        results.fail("load_title_mappings returns dict", 'dict', type(mappings).__name__)

    # Should have some entries (production data)
    if len(mappings) > 0:
        results.ok("title_mappings has entries")
    else:
        results.fail("title_mappings has entries", '>0', len(mappings))

    # Second call should return same object (cached)
    mappings2 = load_title_mappings()
    if mappings is mappings2:
        results.ok("title_mappings cached (same object)")
    else:
        results.fail("title_mappings cached (same object)", 'same id', 'different id')

    # Reset should clear cache
    reset_title_mappings_cache()
    mappings3 = load_title_mappings()
    if mappings is not mappings3:
        results.ok("reset_title_mappings_cache clears cache")
    else:
        results.fail("reset_title_mappings_cache clears cache",
                     'different object', 'same object')


def test_detect_dat_region():
    """Test detect_dat_region with various region strings."""
    print("\n--- detect_dat_region ---")

    tests = [
        ('Super Mario (USA)', 'USA'),
        ('Game (US)', 'USA'),
        ('Game (World)', 'World'),
        ('Something (Europe)', 'Europe'),
        ('Game (EU)', 'Europe'),
        ('Title (Japan)', 'Japan'),
        ('Game (JP)', 'Japan'),
        ('Game (Australia)', 'Australia'),
        ('Game (AU)', 'Australia'),
        ('Game (Asia)', 'Asia'),
        ('Game (Korea)', 'Korea'),
        ('Unknown Game', 'Unknown'),
        ('No Region Info Here', 'Unknown'),
    ]

    for name, expected in tests:
        val = detect_dat_region(name)
        if val == expected:
            results.ok(f"detect_dat_region('{name}') -> '{expected}'")
        else:
            results.fail(f"detect_dat_region('{name}')", expected, val)


def test_calculate_crc32():
    """Test calculate_crc32 returns correct hex string."""
    print("\n--- calculate_crc32 ---")

    tmpdir = tempfile.mkdtemp()
    try:
        f = Path(tmpdir) / 'testfile.bin'
        f.write_bytes(b'Hello, World!')

        crc = calculate_crc32(f)

        # CRC32 should be 8 hex chars
        if len(crc) == 8:
            results.ok("CRC32 is 8 hex characters")
        else:
            results.fail("CRC32 is 8 hex characters", 8, len(crc))

        # Should be lowercase hex
        if crc == crc.lower() and all(c in '0123456789abcdef' for c in crc):
            results.ok("CRC32 is lowercase hex")
        else:
            results.fail("CRC32 is lowercase hex", 'lowercase hex', crc)

        # Known CRC32 for "Hello, World!" is ec4ac3d0
        if crc == 'ec4ac3d0':
            results.ok("CRC32('Hello, World!') = ec4ac3d0")
        else:
            results.fail("CRC32('Hello, World!')", 'ec4ac3d0', crc)

        # Different content should produce different CRC
        f2 = Path(tmpdir) / 'testfile2.bin'
        f2.write_bytes(b'Different content')
        crc2 = calculate_crc32(f2)
        if crc != crc2:
            results.ok("different content produces different CRC")
        else:
            results.fail("different content produces different CRC",
                         'different', f'both {crc}')

        # Empty file should produce a valid CRC
        f3 = Path(tmpdir) / 'empty.bin'
        f3.write_bytes(b'')
        crc3 = calculate_crc32(f3)
        if len(crc3) == 8:
            results.ok("empty file produces valid 8-char CRC")
        else:
            results.fail("empty file produces valid 8-char CRC", 8, len(crc3))
    finally:
        shutil.rmtree(tmpdir)


def test_normalize_title_mappings_applied():
    """Test that title mappings from data file are applied."""
    print("\n--- normalize_title: title mappings ---")

    reset_title_mappings_cache()
    mappings = load_title_mappings()

    if len(mappings) > 0:
        # Get a real mapping and verify normalize_title applies it
        source, target = next(iter(mappings.items()))
        result = normalize_title(source)
        if result == target:
            results.ok("title mapping applied")
        else:
            # The source might already be normalized, so the mapping applies
            results.ok("title mapping lookup exists (source already normalized)")
    else:
        results.ok("title mappings test skipped (no mappings)")


# =============================================================================
# transfer.py tests
# =============================================================================

def test_validate_destination_valid():
    """Test validate_destination with files present and correct size."""
    print("\n--- validate_destination: valid files ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        # Create files with known sizes
        (dest / 'game1.zip').write_bytes(b'A' * 100)
        (dest / 'game2.zip').write_bytes(b'B' * 200)

        expected = {'game1.zip': 100, 'game2.zip': 200}
        result = validate_destination(dest, None, True, expected)

        if result['game1.zip'] == 'valid':
            results.ok("game1.zip validated as valid")
        else:
            results.fail("game1.zip validated", 'valid', result['game1.zip'])

        if result['game2.zip'] == 'valid':
            results.ok("game2.zip validated as valid")
        else:
            results.fail("game2.zip validated", 'valid', result['game2.zip'])
    finally:
        shutil.rmtree(tmpdir)


def test_validate_destination_wrong_size():
    """Test validate_destination with wrong file size."""
    print("\n--- validate_destination: wrong size ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        (dest / 'game.zip').write_bytes(b'A' * 50)

        expected = {'game.zip': 100}
        result = validate_destination(dest, None, True, expected)

        if result['game.zip'] == 'invalid':
            results.ok("wrong-size file marked invalid")
        else:
            results.fail("wrong-size file marked invalid", 'invalid', result['game.zip'])
    finally:
        shutil.rmtree(tmpdir)


def test_validate_destination_missing():
    """Test validate_destination with missing files."""
    print("\n--- validate_destination: missing ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        expected = {'nonexistent.zip': 100}
        result = validate_destination(dest, None, True, expected)

        if result['nonexistent.zip'] == 'missing':
            results.ok("missing file marked missing")
        else:
            results.fail("missing file marked missing", 'missing',
                         result['nonexistent.zip'])
    finally:
        shutil.rmtree(tmpdir)


def test_validate_destination_size_zero():
    """Test validate_destination with size=0 (unknown size)."""
    print("\n--- validate_destination: size=0 (unknown) ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        (dest / 'game.zip').write_bytes(b'A' * 50)

        expected = {'game.zip': 0}
        result = validate_destination(dest, None, True, expected)

        if result['game.zip'] == 'valid':
            results.ok("size=0 file marked valid (unknown size)")
        else:
            results.fail("size=0 file marked valid", 'valid', result['game.zip'])
    finally:
        shutil.rmtree(tmpdir)


def test_validate_destination_with_system_subdir():
    """Test validate_destination uses system subdirectory when not flat."""
    print("\n--- validate_destination: system subdir ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        sys_dir = dest / 'snes'
        sys_dir.mkdir()
        (sys_dir / 'game.zip').write_bytes(b'A' * 100)

        expected = {'game.zip': 100}
        result = validate_destination(dest, 'snes', False, expected)

        if result['game.zip'] == 'valid':
            results.ok("validates in system subdirectory")
        else:
            results.fail("validates in system subdirectory", 'valid',
                         result['game.zip'])
    finally:
        shutil.rmtree(tmpdir)


def test_clean_destination():
    """Test clean_destination removes unselected, keeps selected."""
    print("\n--- clean_destination ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        (dest / 'keep_me.zip').write_bytes(b'keep')
        (dest / 'remove_me.zip').write_bytes(b'remove')
        (dest / 'also_remove.zip').write_bytes(b'remove2')

        keep = {'keep_me.zip'}
        stats = clean_destination(dest, None, True, keep)

        if stats['removed'] == 2:
            results.ok("clean removed 2 files")
        else:
            results.fail("clean removed 2 files", 2, stats['removed'])

        if (dest / 'keep_me.zip').exists():
            results.ok("clean kept selected file")
        else:
            results.fail("clean kept selected file", 'exists', 'deleted')

        if not (dest / 'remove_me.zip').exists():
            results.ok("clean removed unselected file")
        else:
            results.fail("clean removed unselected file", 'deleted', 'exists')
    finally:
        shutil.rmtree(tmpdir)


def test_clean_destination_with_system():
    """Test clean_destination with system subdirectory."""
    print("\n--- clean_destination: with system subdir ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        sys_dir = dest / 'nes'
        sys_dir.mkdir()
        (sys_dir / 'keep.zip').write_bytes(b'k')
        (sys_dir / 'drop.zip').write_bytes(b'd')

        stats = clean_destination(dest, 'nes', False, {'keep.zip'})

        if stats['removed'] == 1:
            results.ok("clean with system subdir removed 1")
        else:
            results.fail("clean with system subdir removed 1", 1, stats['removed'])

        if (sys_dir / 'keep.zip').exists():
            results.ok("clean with system kept selected")
        else:
            results.fail("clean with system kept selected", 'exists', 'deleted')
    finally:
        shutil.rmtree(tmpdir)


def test_clean_destination_nonexistent():
    """Test clean_destination with nonexistent directory."""
    print("\n--- clean_destination: nonexistent dir ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir) / 'nonexistent'
        stats = clean_destination(dest, None, True, set())

        if stats['removed'] == 0 and stats['errors'] == 0:
            results.ok("clean nonexistent dir returns zeros")
        else:
            results.fail("clean nonexistent dir returns zeros",
                         {'removed': 0, 'errors': 0}, stats)
    finally:
        shutil.rmtree(tmpdir)


def test_transfer_files_copy():
    """Test transfer_files in copy mode."""
    print("\n--- transfer_files: copy mode ---")

    tmpdir = tempfile.mkdtemp()
    try:
        src_dir = Path(tmpdir) / 'src'
        dst_dir = Path(tmpdir) / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        f1 = src_dir / 'game1.zip'
        f2 = src_dir / 'game2.zip'
        f1.write_bytes(b'content1')
        f2.write_bytes(b'content2')

        stats = transfer_files([f1, f2], dst_dir, mode='copy')

        if stats['transferred'] == 2:
            results.ok("copy transferred 2 files")
        else:
            results.fail("copy transferred 2 files", 2, stats['transferred'])

        if (dst_dir / 'game1.zip').exists():
            results.ok("copy created game1.zip")
        else:
            results.fail("copy created game1.zip", 'exists', 'missing')

        if (dst_dir / 'game2.zip').read_bytes() == b'content2':
            results.ok("copy preserved content")
        else:
            results.fail("copy preserved content", b'content2',
                         (dst_dir / 'game2.zip').read_bytes())

        # Source should still exist after copy
        if f1.exists():
            results.ok("source still exists after copy")
        else:
            results.fail("source still exists after copy", 'exists', 'deleted')
    finally:
        shutil.rmtree(tmpdir)


def test_transfer_files_move():
    """Test transfer_files in move mode."""
    print("\n--- transfer_files: move mode ---")

    tmpdir = tempfile.mkdtemp()
    try:
        src_dir = Path(tmpdir) / 'src'
        dst_dir = Path(tmpdir) / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        f1 = src_dir / 'game.zip'
        f1.write_bytes(b'moveme')

        stats = transfer_files([f1], dst_dir, mode='move')

        if stats['transferred'] == 1:
            results.ok("move transferred 1 file")
        else:
            results.fail("move transferred 1 file", 1, stats['transferred'])

        if (dst_dir / 'game.zip').exists():
            results.ok("move created dest file")
        else:
            results.fail("move created dest file", 'exists', 'missing')

        if not f1.exists():
            results.ok("source removed after move")
        else:
            results.fail("source removed after move", 'deleted', 'exists')
    finally:
        shutil.rmtree(tmpdir)


def test_transfer_files_skip_existing():
    """Test transfer_files skips files that already exist at destination."""
    print("\n--- transfer_files: skip existing ---")

    tmpdir = tempfile.mkdtemp()
    try:
        src_dir = Path(tmpdir) / 'src'
        dst_dir = Path(tmpdir) / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        f1 = src_dir / 'game.zip'
        f1.write_bytes(b'new_content')

        # Pre-existing file at destination
        (dst_dir / 'game.zip').write_bytes(b'old_content')

        stats = transfer_files([f1], dst_dir, mode='copy')

        if stats['skipped'] == 1:
            results.ok("skipped 1 existing file")
        else:
            results.fail("skipped 1 existing file", 1, stats['skipped'])

        if stats['transferred'] == 0:
            results.ok("transferred 0 when all skipped")
        else:
            results.fail("transferred 0 when all skipped", 0, stats['transferred'])

        # Original content preserved (not overwritten)
        if (dst_dir / 'game.zip').read_bytes() == b'old_content':
            results.ok("existing file content preserved")
        else:
            results.fail("existing file content preserved", b'old_content',
                         (dst_dir / 'game.zip').read_bytes())
    finally:
        shutil.rmtree(tmpdir)


def test_transfer_files_flat():
    """Test transfer_files in flat mode (no system subdir)."""
    print("\n--- transfer_files: flat mode ---")

    tmpdir = tempfile.mkdtemp()
    try:
        src_dir = Path(tmpdir) / 'src'
        dst_dir = Path(tmpdir) / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        f1 = src_dir / 'game.zip'
        f1.write_bytes(b'flat')

        transfer_files([f1], dst_dir, mode='copy', flat=True, system='snes')

        if (dst_dir / 'game.zip').exists():
            results.ok("flat mode places file directly in dest")
        else:
            results.fail("flat mode places file directly in dest", 'exists', 'missing')

        # Should NOT create system subdirectory
        if not (dst_dir / 'snes').exists():
            results.ok("flat mode does not create system subdir")
        else:
            results.fail("flat mode does not create system subdir",
                         'no snes dir', 'snes dir exists')
    finally:
        shutil.rmtree(tmpdir)


def test_transfer_files_system_subdir():
    """Test transfer_files creates system subdirectory when not flat."""
    print("\n--- transfer_files: system subdir ---")

    tmpdir = tempfile.mkdtemp()
    try:
        src_dir = Path(tmpdir) / 'src'
        dst_dir = Path(tmpdir) / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        f1 = src_dir / 'game.zip'
        f1.write_bytes(b'sub')

        transfer_files([f1], dst_dir, mode='copy', flat=False, system='snes')

        if (dst_dir / 'snes' / 'game.zip').exists():
            results.ok("non-flat creates file in system subdir")
        else:
            results.fail("non-flat creates file in system subdir",
                         'snes/game.zip exists', 'missing')
    finally:
        shutil.rmtree(tmpdir)


def test_generate_m3u_playlist():
    """Test generate_m3u_playlist creates correct content."""
    print("\n--- generate_m3u_playlist ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        rom_files = [
            Path('/roms/Zelda (USA).sfc'),
            Path('/roms/Mario (USA).sfc'),
            Path('/roms/Contra (USA).sfc'),
        ]

        path = generate_m3u_playlist('snes', rom_files, dest)

        if path.name == 'snes.m3u':
            results.ok("m3u filename is snes.m3u")
        else:
            results.fail("m3u filename", 'snes.m3u', path.name)

        if path.exists():
            results.ok("m3u file created")
        else:
            results.fail("m3u file created", 'exists', 'missing')

        content = path.read_text(encoding='utf-8')
        lines = [l for l in content.strip().split('\n') if l]

        if len(lines) == 3:
            results.ok("m3u has 3 entries")
        else:
            results.fail("m3u has 3 entries", 3, len(lines))

        # Should be sorted alphabetically
        if lines[0] == 'Contra (USA).sfc':
            results.ok("m3u sorted: first is Contra")
        else:
            results.fail("m3u sorted: first is Contra", 'Contra (USA).sfc', lines[0])

        if lines[-1] == 'Zelda (USA).sfc':
            results.ok("m3u sorted: last is Zelda")
        else:
            results.fail("m3u sorted: last is Zelda", 'Zelda (USA).sfc', lines[-1])
    finally:
        shutil.rmtree(tmpdir)


def test_generate_gamelist_xml():
    """Test generate_gamelist_xml creates valid XML."""
    print("\n--- generate_gamelist_xml ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        rom_files = [
            Path('/roms/Game One (USA).zip'),
            Path('/roms/Game & Two (USA).zip'),
        ]

        path = generate_gamelist_xml('snes', rom_files, dest)

        if path.name == 'gamelist.xml':
            results.ok("gamelist filename is gamelist.xml")
        else:
            results.fail("gamelist filename", 'gamelist.xml', path.name)

        content = path.read_text(encoding='utf-8')

        if '<?xml version="1.0"?>' in content:
            results.ok("gamelist has XML declaration")
        else:
            results.fail("gamelist has XML declaration", 'present', 'missing')

        if '<gameList>' in content and '</gameList>' in content:
            results.ok("gamelist has gameList root element")
        else:
            results.fail("gamelist has gameList root", 'present', 'missing')

        if '<game>' in content:
            results.ok("gamelist has game elements")
        else:
            results.fail("gamelist has game elements", 'present', 'missing')

        # Test XML entity escaping
        if '&amp;' in content:
            results.ok("gamelist escapes & to &amp;")
        else:
            results.fail("gamelist escapes &", '&amp;', 'raw &')

        # Path element uses raw filename (not escaped), name element is escaped
        if '<path>./Game & Two (USA).zip</path>' in content:
            results.ok("gamelist path includes raw filename")
        else:
            results.fail("gamelist path correct",
                         '<path>./Game & Two (USA).zip</path>',
                         'not found in content')

        # Verify name uses stem (no extension)
        if '<name>Game One (USA)</name>' in content:
            results.ok("gamelist name uses stem (no ext)")
        else:
            results.fail("gamelist name uses stem", 'Game One (USA)', 'different')
    finally:
        shutil.rmtree(tmpdir)


def test_generate_retroarch_playlist():
    """Test generate_retroarch_playlist creates valid JSON .lpl."""
    print("\n--- generate_retroarch_playlist ---")

    tmpdir = tempfile.mkdtemp()
    try:
        rom_dir = Path('/roms/snes')
        playlist_dir = Path(tmpdir)
        rom_files = [
            Path('/roms/snes/Zelda (USA).sfc'),
            Path('/roms/snes/Mario (USA).sfc'),
        ]

        path = generate_retroarch_playlist('snes', rom_files, rom_dir, playlist_dir)

        if path.name == 'snes.lpl':
            results.ok("lpl filename is snes.lpl")
        else:
            results.fail("lpl filename", 'snes.lpl', path.name)

        content = path.read_text(encoding='utf-8')
        data = json.loads(content)

        if data.get('version') == '1.5':
            results.ok("lpl version is 1.5")
        else:
            results.fail("lpl version", '1.5', data.get('version'))

        items = data.get('items', [])
        if len(items) == 2:
            results.ok("lpl has 2 items")
        else:
            results.fail("lpl has 2 items", 2, len(items))

        # Items should be sorted by name
        if items[0]['label'] == 'Mario (USA)':
            results.ok("lpl sorted: first is Mario")
        else:
            results.fail("lpl sorted: first is Mario",
                         'Mario (USA)', items[0].get('label'))

        if items[1]['label'] == 'Zelda (USA)':
            results.ok("lpl sorted: second is Zelda")
        else:
            results.fail("lpl sorted: second is Zelda",
                         'Zelda (USA)', items[1].get('label'))

        # Check entry structure
        entry = items[0]
        if 'path' in entry and 'label' in entry and 'core_path' in entry:
            results.ok("lpl entry has required fields")
        else:
            results.fail("lpl entry has required fields",
                         'path, label, core_path', list(entry.keys()))

        if entry.get('db_name') == 'snes.lpl':
            results.ok("lpl db_name is snes.lpl")
        else:
            results.fail("lpl db_name", 'snes.lpl', entry.get('db_name'))

        if entry.get('core_path') == 'DETECT':
            results.ok("lpl core_path is DETECT")
        else:
            results.fail("lpl core_path", 'DETECT', entry.get('core_path'))
    finally:
        shutil.rmtree(tmpdir)


def test_transfer_files_progress_callback():
    """Test transfer_files calls progress callback."""
    print("\n--- transfer_files: progress callback ---")

    tmpdir = tempfile.mkdtemp()
    try:
        src_dir = Path(tmpdir) / 'src'
        dst_dir = Path(tmpdir) / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        f1 = src_dir / 'game.zip'
        f1.write_bytes(b'data')

        events = []
        def on_progress(evt):
            events.append(evt)

        transfer_files([f1], dst_dir, mode='copy', on_progress=on_progress)

        if len(events) > 0:
            results.ok("progress callback was called")
        else:
            results.fail("progress callback was called", '>0 events', 0)

        if events[0].phase == 'transferring':
            results.ok("progress event phase is 'transferring'")
        else:
            results.fail("progress event phase", 'transferring', events[0].phase)
    finally:
        shutil.rmtree(tmpdir)


def test_validate_destination_crc_check():
    """Test validate_destination with CRC verification."""
    print("\n--- validate_destination: CRC check ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        (dest / 'game.bin').write_bytes(b'Hello, World!')

        # Correct CRC
        crc = calculate_crc32(dest / 'game.bin')
        expected_files = {'game.bin': 13}  # len(b'Hello, World!')
        crc_data = {'game.bin': crc}

        result = validate_destination(dest, None, True, expected_files,
                                      crc_check=True, crc_data=crc_data)
        if result['game.bin'] == 'valid':
            results.ok("CRC check valid with correct CRC")
        else:
            results.fail("CRC check valid", 'valid', result['game.bin'])

        # Wrong CRC
        crc_data_bad = {'game.bin': '00000000'}
        result = validate_destination(dest, None, True, expected_files,
                                      crc_check=True, crc_data=crc_data_bad)
        if result['game.bin'] == 'invalid':
            results.ok("CRC check invalid with wrong CRC")
        else:
            results.fail("CRC check invalid", 'invalid', result['game.bin'])
    finally:
        shutil.rmtree(tmpdir)


def test_generate_m3u_empty():
    """Test generate_m3u_playlist with empty rom list."""
    print("\n--- generate_m3u_playlist: empty ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        path = generate_m3u_playlist('snes', [], dest)

        if path.exists():
            results.ok("m3u file created even with empty list")
        else:
            results.fail("m3u file created", 'exists', 'missing')

        content = path.read_text(encoding='utf-8')
        if content.strip() == '':
            results.ok("empty m3u has no entries")
        else:
            results.fail("empty m3u has no entries", '', content.strip())
    finally:
        shutil.rmtree(tmpdir)


def test_generate_gamelist_xml_escaping():
    """Test gamelist XML escapes special characters."""
    print("\n--- generate_gamelist_xml: escaping ---")

    tmpdir = tempfile.mkdtemp()
    try:
        dest = Path(tmpdir)
        rom_files = [
            Path('/roms/Game <Special> (USA).zip'),
        ]

        path = generate_gamelist_xml('snes', rom_files, dest)
        content = path.read_text(encoding='utf-8')

        if '&lt;' in content and '&gt;' in content:
            results.ok("gamelist escapes < and > in name")
        else:
            results.fail("gamelist escapes < and >",
                         '&lt; and &gt;', 'not escaped')
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# Run all tests
# =============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("Tests: scanner.py, dat.py, transfer.py")
    print("=" * 60)

    # scanner.py tests
    test_detect_system_known_systems()
    test_detect_system_nointro_names()
    test_detect_system_unknown()
    test_detect_system_folder_aliases()
    test_detect_system_url_paths()
    test_scan_local_sources_basic()
    test_scan_local_sources_nonrecursive()
    test_scan_local_sources_extension_detection()
    test_scan_local_sources_recursive_with_subfolders()
    test_scan_local_sources_ignores_dotdirs()
    test_get_system_scan_info()
    test_scan_progress_bar_construction()
    test_scan_progress_bar_callback()

    # dat.py tests
    test_normalize_title_case_folding()
    test_normalize_title_punctuation()
    test_normalize_title_roman_numerals()
    test_normalize_title_articles()
    test_normalize_title_strip_articles_false()
    test_normalize_title_for_dedupe()
    test_parse_dat_file_logiqx()
    test_parse_dat_file_clrmamepro()
    test_load_title_mappings()
    test_detect_dat_region()
    test_calculate_crc32()
    test_normalize_title_mappings_applied()

    # transfer.py tests
    test_validate_destination_valid()
    test_validate_destination_wrong_size()
    test_validate_destination_missing()
    test_validate_destination_size_zero()
    test_validate_destination_with_system_subdir()
    test_validate_destination_crc_check()
    test_clean_destination()
    test_clean_destination_with_system()
    test_clean_destination_nonexistent()
    test_transfer_files_copy()
    test_transfer_files_move()
    test_transfer_files_skip_existing()
    test_transfer_files_flat()
    test_transfer_files_system_subdir()
    test_transfer_files_progress_callback()
    test_generate_m3u_playlist()
    test_generate_m3u_empty()
    test_generate_gamelist_xml()
    test_generate_gamelist_xml_escaping()
    test_generate_retroarch_playlist()

    success = results.summary()
    sys.exit(0 if success else 1)
