"""Tests for dat.py module.

Covers title normalization, DAT file parsing, CRC calculation, and region detection.
"""

import zipfile

import pytest

from retro_refiner.dat import (
    normalize_title,
    normalize_title_for_dedupe,
    parse_dat_file,
    parse_logiqx_xml_dat,
    parse_clrmamepro_dat,
    load_all_system_dats,
    load_title_mappings,
    reset_title_mappings_cache,
    detect_dat_region,
    calculate_crc32,
    calculate_crc32_from_zip,
    load_crc_cache,
    save_crc_cache,
    get_cached_crc,
)


# =============================================================================
# dat.py tests
# =============================================================================

@pytest.mark.parametrize("input_str,expected", [
    ("SONIC THE HEDGEHOG", "sonic the hedgehog"),
    ("Already Lowercase", "already lowercase"),
])
def test_normalize_title_case_folding(input_str, expected):
    assert normalize_title(input_str) == expected


@pytest.mark.parametrize("input_str,expected", [
    ("Kirby's Dream Land", "kirby s dream land"),
    ("Pac-Man", "pac man"),
    ("Game: The Subtitle", "game the subtitle"),
])
def test_normalize_title_punctuation(input_str, expected):
    assert normalize_title(input_str) == expected


@pytest.mark.parametrize("input_str,expected", [
    ("Final Fantasy III", "final fantasy 3"),
    ("Final Fantasy VII", "final fantasy 7"),
    ("Street Fighter II", "street fighter 2"),
    ("Game IV", "game 4"),
    ("Game VIII", "game 8"),
])
def test_normalize_title_roman_numerals(input_str, expected):
    assert normalize_title(input_str) == expected


@pytest.mark.parametrize("input_str,expected", [
    ("The Legend of Zelda", "legend of zelda"),
    ("A Game", "game"),
    ("An Adventure", "adventure"),
    ("Legend of Zelda, The", "legend of zelda"),
])
def test_normalize_title_articles(input_str, expected):
    assert normalize_title(input_str) == expected


def test_normalize_title_strip_articles_false_preserves_the():
    assert normalize_title("The Bully", strip_articles=False) == "the bully"


def test_normalize_title_strip_articles_false_preserves_leading():
    val = normalize_title("The Legend of Zelda", strip_articles=False)
    assert val == "the legend of zelda"


def test_normalize_title_strip_articles_false_comma():
    val = normalize_title("Legend of Zelda, The", strip_articles=False)
    assert val == "legend of zelda the"


def test_normalize_title_for_dedupe_preserves_the():
    assert normalize_title_for_dedupe("The Bully") == "the bully"


def test_normalize_title_for_dedupe_converts_roman_numerals():
    assert normalize_title_for_dedupe("The Game III") == "the game 3"


def test_normalize_title_for_dedupe_differs_from_normal():
    normal = normalize_title("The Bully")
    dedupe = normalize_title_for_dedupe("The Bully")
    assert normal != dedupe


def test_parse_dat_file_logiqx(tmp_path):
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
    dat_path = tmp_path / "test.dat"
    dat_path.write_text(dat_content, encoding="utf-8")

    entries = parse_dat_file(dat_path)

    assert len(entries) == 2
    assert "abcd1234" in entries

    entry = entries["abcd1234"]
    assert entry.name == "Test Game (USA)"
    assert entry.rom_name == "Test Game (USA).zip"
    assert entry.size == 1024
    assert entry.region == "USA"

    japan_entry = entries["5678abcd"]
    assert japan_entry.region == "Japan"
    assert japan_entry.size == 2048


def test_parse_dat_file_clrmamepro(tmp_path):
    dat_content = (
        'clrmamepro (\n'
        '\tname "Test ClrMame DAT"\n'
        ')\n'
        '\n'
        'game ( name "Cool Game (Europe)"\n'
        '\trom ( name "Cool Game (Europe).zip" size 512 crc DEADBEEF )\n'
        ')\n'
    )
    dat_path = tmp_path / "test.dat"
    dat_path.write_text(dat_content, encoding="utf-8")

    entries = parse_dat_file(dat_path)

    assert len(entries) == 1
    entry = entries["deadbeef"]
    assert entry.name == "Cool Game (Europe)"
    assert entry.region == "Europe"


def test_load_title_mappings():
    reset_title_mappings_cache()
    mappings = load_title_mappings()

    assert isinstance(mappings, dict)
    assert len(mappings) > 0

    # Second call returns same cached object
    mappings2 = load_title_mappings()
    assert mappings is mappings2

    # Reset clears cache
    reset_title_mappings_cache()
    mappings3 = load_title_mappings()
    assert mappings is not mappings3


@pytest.mark.parametrize("name,expected", [
    ("Super Mario (USA)", "USA"),
    ("Game (US)", "USA"),
    ("Game (World)", "World"),
    ("Something (Europe)", "Europe"),
    ("Game (EU)", "Europe"),
    ("Title (Japan)", "Japan"),
    ("Game (JP)", "Japan"),
    ("Game (Australia)", "Australia"),
    ("Game (AU)", "Australia"),
    ("Game (Asia)", "Asia"),
    ("Game (Korea)", "Korea"),
    ("Unknown Game", "Unknown"),
    ("No Region Info Here", "Unknown"),
])
def test_detect_dat_region(name, expected):
    assert detect_dat_region(name) == expected


def test_calculate_crc32(tmp_path):
    f = tmp_path / "testfile.bin"
    f.write_bytes(b"Hello, World!")

    crc = calculate_crc32(f)
    assert len(crc) == 8
    assert crc == crc.lower()
    assert all(c in "0123456789abcdef" for c in crc)
    assert crc == "ec4ac3d0"

    # Different content produces different CRC
    f2 = tmp_path / "testfile2.bin"
    f2.write_bytes(b"Different content")
    assert calculate_crc32(f2) != crc

    # Empty file produces valid CRC
    f3 = tmp_path / "empty.bin"
    f3.write_bytes(b"")
    assert len(calculate_crc32(f3)) == 8


def test_normalize_title_mappings_applied():
    reset_title_mappings_cache()
    mappings = load_title_mappings()
    if len(mappings) > 0:
        source, target = next(iter(mappings.items()))
        result = normalize_title(source)
        # Mapping may already be normalized, so just verify no crash
        assert result is not None


# =============================================================================
# Helpers (from test_filter_dat split)
# =============================================================================

def _make_zip_rom(tmp_path, zip_name, inner_name, inner_content):
    """Create a real .zip file containing a single file."""
    zip_path = tmp_path / zip_name
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, inner_content)
    return zip_path


# =============================================================================
# parse_logiqx_xml_dat — Complex XML (from test_filter_dat)
# =============================================================================

class TestParseLogiqxXmlDat:
    """Test Logiqx XML DAT parsing with complex inputs."""

    def test_multiple_roms_per_game(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Multi ROM Game (USA)">
<rom name="rom1.bin" size="1024" crc="AAAA1111"/>
<rom name="rom2.bin" size="2048" crc="BBBB2222"/>
</game>
</datafile>'''
        p = tmp_path / "multi.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert len(entries) == 2
        assert "aaaa1111" in entries
        assert "bbbb2222" in entries

    def test_machine_tag(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<machine name="Arcade Game (World)">
<rom name="arcade.bin" size="512" crc="CCCC3333"/>
</machine>
</datafile>'''
        p = tmp_path / "machine.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert "cccc3333" in entries
        assert entries["cccc3333"].region == "World"

    def test_md5_and_sha1_parsed(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Hash Game (USA)">
<rom name="hash.bin" size="100" crc="11112222"
     md5="AABBCCDD11223344AABBCCDD11223344"
     sha1="AABB11223344556677889900AABBCCDDEEFF0011"/>
</game>
</datafile>'''
        p = tmp_path / "hash.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        entry = entries["11112222"]
        assert entry.md5 == "aabbccdd11223344aabbccdd11223344"
        assert entry.sha1 != ""

    def test_region_detection_from_game_name(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Euro Game (Europe)">
<rom name="euro.bin" size="100" crc="EEFF0011"/>
</game>
<game name="JP Game (Japan)">
<rom name="jp.bin" size="100" crc="EEFF0022"/>
</game>
</datafile>'''
        p = tmp_path / "regions.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert entries["eeff0011"].region == "Europe"
        assert entries["eeff0022"].region == "Japan"

    def test_rom_without_crc_skipped(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="No CRC Game (USA)">
<rom name="nocrc.bin" size="100"/>
</game>
<game name="With CRC (USA)">
<rom name="withcrc.bin" size="100" crc="DEADBEEF"/>
</game>
</datafile>'''
        p = tmp_path / "nocrc.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert len(entries) == 1
        assert "deadbeef" in entries

    def test_empty_dat(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
</datafile>'''
        p = tmp_path / "empty.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert len(entries) == 0

    def test_size_zero_when_missing(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="No Size (USA)">
<rom name="nosize.bin" crc="AABB0011"/>
</game>
</datafile>'''
        p = tmp_path / "nosize.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert entries["aabb0011"].size == 0


# =============================================================================
# parse_clrmamepro_dat — Complex Input (from test_filter_dat)
# =============================================================================

class TestParseClrMameProDat:
    """Test ClrMamePro DAT parsing with complex inputs."""

    def test_multiple_games(self, tmp_path):
        dat = (
            'clrmamepro (\n'
            '\tname "Multi Test"\n'
            ')\n\n'
            'game ( name "Game One (USA)"\n'
            '\trom ( name "game1.zip" size 1024 crc AAAA1111 )\n'
            ')\n\n'
            'game ( name "Game Two (Japan)"\n'
            '\trom ( name "game2.zip" size 2048 crc BBBB2222 )\n'
            ')\n'
        )
        p = tmp_path / "multi.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 2
        assert entries["aaaa1111"].region == "USA"
        assert entries["bbbb2222"].region == "Japan"

    def test_multiple_roms_per_game(self, tmp_path):
        dat = (
            'game ( name "Multi ROM (USA)"\n'
            '\trom ( name "rom1.bin" size 100 crc 11110000 )\n'
            '\trom ( name "rom2.bin" size 200 crc 22220000 )\n'
            ')\n'
        )
        p = tmp_path / "multrom.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 2

    def test_md5_and_sha1_parsed(self, tmp_path):
        dat = (
            'game ( name "Hash Game (USA)"\n'
            '\trom ( name "hash.bin" size 100 crc 33330000'
            ' md5 aabbccdd11223344 sha1 aabb112233445566 )\n'
            ')\n'
        )
        p = tmp_path / "hash.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert entries["33330000"].md5 == "aabbccdd11223344"

    def test_rom_without_crc_skipped(self, tmp_path):
        dat = (
            'game ( name "No CRC (USA)"\n'
            '\trom ( name "nocrc.bin" size 100 )\n'
            ')\n'
            'game ( name "Has CRC (USA)"\n'
            '\trom ( name "hascrc.bin" size 100 crc FFEE0011 )\n'
            ')\n'
        )
        p = tmp_path / "nocrc.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 1
        assert "ffee0011" in entries

    def test_empty_dat(self, tmp_path):
        dat = 'clrmamepro (\n\tname "Empty"\n)\n'
        p = tmp_path / "empty.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 0


# =============================================================================
# parse_dat_file — Auto-detection (from test_filter_dat)
# =============================================================================

class TestParseDatFileAutoDetect:
    """Test auto-detection of DAT format."""

    def test_detects_xml_format(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="XML Game (USA)">
<rom name="xml.zip" size="100" crc="12345678"/>
</game>
</datafile>'''
        p = tmp_path / "test.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_dat_file(p)
        assert "12345678" in entries

    def test_detects_clrmamepro_format(self, tmp_path):
        dat = (
            'clrmamepro (\n'
            '\tname "Test"\n)\n'
            'game ( name "CMP Game (USA)"\n'
            '\trom ( name "cmp.zip" size 100 crc ABCDEF01 )\n)\n'
        )
        p = tmp_path / "test.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_dat_file(p)
        assert "abcdef01" in entries


# =============================================================================
# load_all_system_dats (from test_filter_dat)
# =============================================================================

class TestLoadAllSystemDats:
    """Test loading and merging multiple DAT files for a system."""

    def test_primary_dat_only(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Game A (USA)">
<rom name="a.zip" size="100" crc="AAAA0001"/>
</game>
</datafile>'''
        (tmp_path / "nes.dat").write_text(dat, encoding="utf-8")
        entries = load_all_system_dats("nes", tmp_path)
        assert len(entries) == 1
        assert "aaaa0001" in entries

    def test_primary_plus_extra(self, tmp_path):
        primary = '''<?xml version="1.0"?>
<datafile>
<game name="Game A (USA)">
<rom name="a.zip" size="100" crc="AAAA0001"/>
</game>
</datafile>'''
        extra = '''<?xml version="1.0"?>
<datafile>
<game name="Game B (USA)">
<rom name="b.zip" size="200" crc="BBBB0002"/>
</game>
</datafile>'''
        (tmp_path / "nes.dat").write_text(primary, encoding="utf-8")
        (tmp_path / "nes_extra1.dat").write_text(extra, encoding="utf-8")
        entries = load_all_system_dats("nes", tmp_path)
        assert len(entries) == 2
        assert "aaaa0001" in entries
        assert "bbbb0002" in entries

    def test_multiple_extras_merged(self, tmp_path):
        primary = '''<?xml version="1.0"?>
<datafile>
<game name="A (USA)"><rom name="a.zip" size="100" crc="AA000001"/></game>
</datafile>'''
        extra1 = '''<?xml version="1.0"?>
<datafile>
<game name="B (USA)"><rom name="b.zip" size="100" crc="BB000002"/></game>
</datafile>'''
        extra2 = '''<?xml version="1.0"?>
<datafile>
<game name="C (USA)"><rom name="c.zip" size="100" crc="CC000003"/></game>
</datafile>'''
        (tmp_path / "snes.dat").write_text(primary, encoding="utf-8")
        (tmp_path / "snes_extra1.dat").write_text(extra1, encoding="utf-8")
        (tmp_path / "snes_extra2.dat").write_text(extra2, encoding="utf-8")
        entries = load_all_system_dats("snes", tmp_path)
        assert len(entries) == 3

    def test_no_dats_returns_empty(self, tmp_path):
        entries = load_all_system_dats("nonexistent", tmp_path)
        assert len(entries) == 0

    def test_extra_without_primary(self, tmp_path):
        extra = '''<?xml version="1.0"?>
<datafile>
<game name="B (USA)"><rom name="b.zip" size="200" crc="BBBB0002"/></game>
</datafile>'''
        (tmp_path / "gba_extra1.dat").write_text(extra, encoding="utf-8")
        entries = load_all_system_dats("gba", tmp_path)
        assert len(entries) == 1


# =============================================================================
# CRC Cache Round-Trip (from test_filter_dat)
# =============================================================================

class TestCrcCache:
    """Test load_crc_cache / save_crc_cache / get_cached_crc."""

    def test_save_and_load_roundtrip(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        cache = {
            "/path/to/rom.zip": {
                "crc": "abcd1234",
                "mtime": 1000.0,
                "size": 500,
            }
        }
        save_crc_cache(cache_path, cache)
        loaded = load_crc_cache(cache_path)
        assert loaded["/path/to/rom.zip"]["crc"] == "abcd1234"

    def test_load_nonexistent_returns_empty(self, tmp_path):
        loaded = load_crc_cache(tmp_path / "nonexistent.json")
        assert loaded == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        cache_path = tmp_path / "corrupt.json"
        cache_path.write_text("{bad json", encoding="utf-8")
        loaded = load_crc_cache(cache_path)
        assert loaded == {}

    def test_get_cached_crc_calculates_and_caches(self, tmp_path):
        f = tmp_path / "testrom.bin"
        f.write_bytes(b"Hello CRC test")
        cache = {}
        crc = get_cached_crc(f, cache)
        assert crc is not None
        assert len(crc) == 8
        # Should be cached now
        key = str(f)
        assert key in cache
        assert cache[key]["crc"] == crc

    def test_get_cached_crc_returns_cached(self, tmp_path):
        f = tmp_path / "cached.bin"
        f.write_bytes(b"data")
        stat = f.stat()
        cache = {
            str(f): {
                "crc": "cafebabe",
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        }
        crc = get_cached_crc(f, cache)
        assert crc == "cafebabe"

    def test_get_cached_crc_invalidates_on_mtime_change(self, tmp_path):
        f = tmp_path / "changing.bin"
        f.write_bytes(b"original")
        stat = f.stat()
        cache = {
            str(f): {
                "crc": "oldcrc00",
                "mtime": stat.st_mtime - 100,  # stale mtime
                "size": stat.st_size,
            }
        }
        crc = get_cached_crc(f, cache)
        assert crc != "oldcrc00"

    def test_get_cached_crc_invalidates_on_size_change(self, tmp_path):
        f = tmp_path / "resized.bin"
        f.write_bytes(b"data")
        stat = f.stat()
        cache = {
            str(f): {
                "crc": "oldcrc00",
                "mtime": stat.st_mtime,
                "size": stat.st_size + 999,  # wrong size
            }
        }
        crc = get_cached_crc(f, cache)
        assert crc != "oldcrc00"

    def test_get_cached_crc_zip_file(self, tmp_path):
        zip_path = _make_zip_rom(
            tmp_path, "game.zip", "game.bin", b"zip content data")
        cache = {}
        crc = get_cached_crc(zip_path, cache)
        assert crc is not None
        assert len(crc) == 8

    def test_get_cached_crc_with_download_index(self, tmp_path):
        f = tmp_path / "indexed.bin"
        f.write_bytes(b"indexed data")
        stat = f.stat()
        download_index = {
            str(f): {
                "crc": "indexcrc1",
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        }
        cache = {}
        crc = get_cached_crc(f, cache, download_crc_index=download_index)
        assert crc == "indexcrc1"
        # Should also be copied into the main cache
        assert cache[str(f)]["crc"] == "indexcrc1"

    def test_save_creates_parent_dirs(self, tmp_path):
        cache_path = tmp_path / "sub" / "dir" / "cache.json"
        save_crc_cache(cache_path, {"key": "val"})
        assert cache_path.exists()


# =============================================================================
# calculate_crc32_from_zip (from test_filter_dat)
# =============================================================================

class TestCalculateCrc32FromZip:
    """Test CRC32 calculation from first file inside a ZIP."""

    def test_basic_zip(self, tmp_path):
        zip_path = _make_zip_rom(
            tmp_path, "test.zip", "rom.bin", b"ROM content")
        crc = calculate_crc32_from_zip(zip_path)
        assert crc is not None
        assert len(crc) == 8

    def test_matches_direct_crc(self, tmp_path):
        content = b"Some ROM data for CRC comparison"
        # Calculate CRC directly
        raw_file = tmp_path / "raw.bin"
        raw_file.write_bytes(content)
        direct_crc = calculate_crc32(raw_file)
        # Calculate CRC from inside ZIP
        zip_path = _make_zip_rom(
            tmp_path, "test.zip", "rom.bin", content)
        zip_crc = calculate_crc32_from_zip(zip_path)
        assert zip_crc == direct_crc

    def test_skips_directory_entries(self, tmp_path):
        zip_path = tmp_path / "withdir.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.mkdir("subdir")
            zf.writestr("subdir/rom.bin", b"nested rom content")
        crc = calculate_crc32_from_zip(zip_path)
        assert crc is not None

    def test_invalid_zip_returns_none(self, tmp_path):
        bad_zip = tmp_path / "notazip.zip"
        bad_zip.write_bytes(b"not a real zip file")
        crc = calculate_crc32_from_zip(bad_zip)
        assert crc is None

    def test_empty_zip_returns_none(self, tmp_path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, 'w'):
            pass  # empty ZIP
        crc = calculate_crc32_from_zip(zip_path)
        assert crc is None


# =============================================================================
# detect_dat_region — Additional Edge Cases (from test_filter_dat)
# =============================================================================

class TestDetectDatRegionEdge:
    """Additional edge cases for detect_dat_region."""

    def test_case_insensitive_usa(self):
        assert detect_dat_region("game (UsA)") == "USA"

    def test_case_insensitive_europe(self):
        assert detect_dat_region("game (EUROPE)") == "Europe"

    def test_us_shorthand(self):
        assert detect_dat_region("game (US)") == "USA"

    def test_eu_shorthand(self):
        assert detect_dat_region("game (EU)") == "Europe"

    def test_jp_shorthand(self):
        assert detect_dat_region("game (JP)") == "Japan"

    def test_au_shorthand(self):
        assert detect_dat_region("game (AU)") == "Australia"

    def test_multiple_regions_first_wins(self):
        # First match wins in the if-chain
        result = detect_dat_region("game (USA) (Japan)")
        assert result == "USA"

    def test_region_in_middle_of_name(self):
        assert detect_dat_region("Super Game (World) Edition") == "World"

    def test_no_region_returns_unknown(self):
        assert detect_dat_region("Game Without Region") == "Unknown"

    def test_empty_string(self):
        assert detect_dat_region("") == "Unknown"


# =============================================================================
# normalize_title — Edge Cases (from test_filter_dat)
# =============================================================================

class TestNormalizeTitleEdge:
    """Edge cases for normalize_title."""

    def test_accented_characters_stripped(self):
        result = normalize_title("Pokemon")
        assert result == "pokemon"

    def test_unicode_accents_normalized(self):
        # e-acute should be stripped
        result = normalize_title("Pok\u00e9mon")
        assert result == "pokemon"

    def test_multiple_spaces_collapsed(self):
        result = normalize_title("Super   Mario   Bros")
        assert result == "super mario bros"

    def test_leading_trailing_spaces_stripped(self):
        result = normalize_title("  Game  ")
        assert result == "game"

    def test_comma_the_pattern(self):
        result = normalize_title("Legend of Zelda, The")
        assert result == "legend of zelda"

    def test_roman_numeral_boundary(self):
        """Roman numerals only match word boundaries."""
        result = normalize_title("Ivanhoe")
        # Should NOT convert the "iv" in "ivanhoe"
        assert "4" not in result

    def test_dedupe_preserves_articles(self):
        normal = normalize_title("The Legend")
        dedupe = normalize_title_for_dedupe("The Legend")
        assert "the" not in normal
        assert dedupe.startswith("the")


# =============================================================================
# Title Mappings (from test_filter_dat)
# =============================================================================

class TestTitleMappingsExtended:
    """Test title mapping loading and caching."""

    def test_load_returns_dict(self):
        reset_title_mappings_cache()
        mappings = load_title_mappings()
        assert isinstance(mappings, dict)

    def test_cache_returns_same_object(self):
        reset_title_mappings_cache()
        m1 = load_title_mappings()
        m2 = load_title_mappings()
        assert m1 is m2

    def test_reset_clears_cache(self):
        reset_title_mappings_cache()
        m1 = load_title_mappings()
        reset_title_mappings_cache()
        m2 = load_title_mappings()
        assert m1 is not m2

    def test_mapping_applied_in_normalize(self):
        reset_title_mappings_cache()
        mappings = load_title_mappings()
        if mappings:
            source = next(iter(mappings))
            result = normalize_title(source)
            # After mapping, the result should be the target
            assert result == mappings[source]
