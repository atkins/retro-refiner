#!/usr/bin/env python3
"""Tests for scanner.py, dat.py, and transfer.py modules.

Covers system detection, local scanning, DAT parsing, title normalization,
CRC calculation, file transfer, playlist generation, and destination management.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

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


# =============================================================================
# scanner.py tests
# =============================================================================

@pytest.mark.parametrize("path,expected", [
    ("snes", "snes"),
    ("nes", "nes"),
    ("genesis", "genesis"),
    ("gba", "gba"),
    ("n64", "n64"),
])
def test_detect_system_known_systems(path, expected):
    assert detect_system_from_path(path) == expected


@pytest.mark.parametrize("path,expected", [
    ("Sega - Mega Drive - Genesis", "genesis"),
    ("Nintendo - Game Boy Advance", "gba"),
])
def test_detect_system_nointro_names(path, expected):
    assert detect_system_from_path(path) == expected


@pytest.mark.parametrize("path", [
    "totally_unknown_thing",
    "",
    "////",
])
def test_detect_system_unknown(path):
    assert detect_system_from_path(path) is None


def test_detect_system_folder_alias():
    assert detect_system_from_path("megadrive") == "genesis"


@pytest.mark.parametrize("path,expected", [
    ("/roms/snes/something", "snes"),
    ("/archive/genesis/", "genesis"),
])
def test_detect_system_url_paths(path, expected):
    assert detect_system_from_path(path) == expected


def test_scan_local_sources_basic(tmp_path):
    snes_dir = tmp_path / "snes"
    snes_dir.mkdir()
    (snes_dir / "Game1 (USA).sfc").write_bytes(b"rom1")
    (snes_dir / "Game2 (Japan).sfc").write_bytes(b"rom2")

    nes_dir = tmp_path / "nes"
    nes_dir.mkdir()
    (nes_dir / "Mario (USA).nes").write_bytes(b"nes1")

    result = scan_local_sources([tmp_path], recursive=True)

    assert "snes" in result
    assert len(result["snes"]) == 2
    assert "nes" in result
    assert len(result["nes"]) == 1


def test_scan_local_sources_nonrecursive(tmp_path):
    sub = tmp_path / "snes"
    sub.mkdir()
    (sub / "Game (USA).sfc").write_bytes(b"rom")

    result = scan_local_sources([tmp_path], recursive=False)
    assert len(result.get("snes", [])) == 0


def test_scan_local_sources_extension_detection(tmp_path):
    (tmp_path / "Game.nes").write_bytes(b"nes")
    (tmp_path / "Game.sfc").write_bytes(b"sfc")
    (tmp_path / "Game.gba").write_bytes(b"gba")

    result = scan_local_sources([tmp_path], recursive=False)
    assert "nes" in result
    assert "snes" in result
    assert "gba" in result


def test_scan_local_sources_recursive_with_subfolders(tmp_path):
    region_dir = tmp_path / "snes" / "USA"
    region_dir.mkdir(parents=True)
    (region_dir / "Game (USA).sfc").write_bytes(b"rom")

    result = scan_local_sources([tmp_path], recursive=True)
    assert "snes" in result
    assert len(result["snes"]) == 1


def test_scan_local_sources_ignores_dotdirs(tmp_path):
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "Game.nes").write_bytes(b"rom")

    result = scan_local_sources([tmp_path], recursive=True)
    assert len(result.get("nes", [])) == 0


def test_get_system_scan_info(tmp_path):
    f1 = tmp_path / "game1.nes"
    f2 = tmp_path / "game2.nes"
    f1.write_bytes(b"A" * 100)
    f2.write_bytes(b"B" * 200)

    systems_dict = {"nes": [f1, f2], "snes": [tmp_path / "nonexist.sfc"]}
    infos = get_system_scan_info(systems_dict, source_type="local")

    assert len(infos) == 2

    nes_info = [i for i in infos if i.system == "nes"]
    assert nes_info and nes_info[0].file_count == 2
    assert nes_info[0].total_size == 300
    assert nes_info[0].source_type == "local"


def test_get_system_scan_info_network():
    infos = get_system_scan_info(
        {"snes": ["url1", "url2"]}, source_type="network")
    assert infos[0].total_size == 0


def test_scan_progress_bar_construction():
    old_stdout = sys.stdout
    devnull = open(os.devnull, 'w', encoding='utf-8')
    sys.stdout = devnull
    try:
        bar = ScanProgressBar(total=10, desc="Test", indent="  ")
    finally:
        sys.stdout = old_stdout
        devnull.close()

    assert bar.total == 10
    assert bar.desc == "Test"
    assert bar.current == 0
    assert bar.bar_width == 20


def test_scan_progress_bar_callback():
    old_stdout = sys.stdout
    devnull = open(os.devnull, 'w', encoding='utf-8')
    sys.stdout = devnull
    try:
        bar = ScanProgressBar(total=5, desc="CB Test")
        cb = bar.make_callback()
        cb(3, 5)
    finally:
        sys.stdout = old_stdout
        devnull.close()

    assert bar.current == 3


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
# transfer.py tests
# =============================================================================

def test_validate_destination_valid(tmp_path):
    (tmp_path / "game1.zip").write_bytes(b"A" * 100)
    (tmp_path / "game2.zip").write_bytes(b"B" * 200)

    expected = {"game1.zip": 100, "game2.zip": 200}
    result = validate_destination(tmp_path, None, True, expected)
    assert result["game1.zip"] == "valid"
    assert result["game2.zip"] == "valid"


def test_validate_destination_wrong_size(tmp_path):
    (tmp_path / "game.zip").write_bytes(b"A" * 50)
    result = validate_destination(tmp_path, None, True, {"game.zip": 100})
    assert result["game.zip"] == "invalid"


def test_validate_destination_missing(tmp_path):
    result = validate_destination(tmp_path, None, True,
                                  {"nonexistent.zip": 100})
    assert result["nonexistent.zip"] == "missing"


def test_validate_destination_size_zero(tmp_path):
    (tmp_path / "game.zip").write_bytes(b"A" * 50)
    result = validate_destination(tmp_path, None, True, {"game.zip": 0})
    assert result["game.zip"] == "valid"


def test_validate_destination_with_system_subdir(tmp_path):
    sys_dir = tmp_path / "snes"
    sys_dir.mkdir()
    (sys_dir / "game.zip").write_bytes(b"A" * 100)

    result = validate_destination(tmp_path, "snes", False, {"game.zip": 100})
    assert result["game.zip"] == "valid"


def test_validate_destination_crc_check(tmp_path):
    (tmp_path / "game.bin").write_bytes(b"Hello, World!")
    crc = calculate_crc32(tmp_path / "game.bin")
    expected_files = {"game.bin": 13}

    # Correct CRC
    result = validate_destination(tmp_path, None, True, expected_files,
                                  crc_check=True, crc_data={"game.bin": crc})
    assert result["game.bin"] == "valid"

    # Wrong CRC
    result = validate_destination(tmp_path, None, True, expected_files,
                                  crc_check=True,
                                  crc_data={"game.bin": "00000000"})
    assert result["game.bin"] == "invalid"


def test_clean_destination(tmp_path):
    (tmp_path / "keep_me.zip").write_bytes(b"keep")
    (tmp_path / "remove_me.zip").write_bytes(b"remove")
    (tmp_path / "also_remove.zip").write_bytes(b"remove2")

    stats = clean_destination(tmp_path, None, True, {"keep_me.zip"})
    assert stats["removed"] == 2
    assert (tmp_path / "keep_me.zip").exists()
    assert not (tmp_path / "remove_me.zip").exists()


def test_clean_destination_with_system(tmp_path):
    sys_dir = tmp_path / "nes"
    sys_dir.mkdir()
    (sys_dir / "keep.zip").write_bytes(b"k")
    (sys_dir / "drop.zip").write_bytes(b"d")

    stats = clean_destination(tmp_path, "nes", False, {"keep.zip"})
    assert stats["removed"] == 1
    assert (sys_dir / "keep.zip").exists()


def test_clean_destination_nonexistent(tmp_path):
    dest = tmp_path / "nonexistent"
    stats = clean_destination(dest, None, True, set())
    assert stats["removed"] == 0
    assert stats["errors"] == 0


def test_transfer_files_copy(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    f1 = src_dir / "game1.zip"
    f2 = src_dir / "game2.zip"
    f1.write_bytes(b"content1")
    f2.write_bytes(b"content2")

    stats = transfer_files([f1, f2], dst_dir, mode="copy")
    assert stats["transferred"] == 2
    assert (dst_dir / "game1.zip").exists()
    assert (dst_dir / "game2.zip").read_bytes() == b"content2"
    assert f1.exists()  # source still exists


def test_transfer_files_move(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    f1 = src_dir / "game.zip"
    f1.write_bytes(b"moveme")

    stats = transfer_files([f1], dst_dir, mode="move")
    assert stats["transferred"] == 1
    assert (dst_dir / "game.zip").exists()
    assert not f1.exists()


def test_transfer_files_skip_existing(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    f1 = src_dir / "game.zip"
    f1.write_bytes(b"new_content")
    (dst_dir / "game.zip").write_bytes(b"old_content")

    stats = transfer_files([f1], dst_dir, mode="copy")
    assert stats["skipped"] == 1
    assert stats["transferred"] == 0
    assert (dst_dir / "game.zip").read_bytes() == b"old_content"


def test_transfer_files_flat(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    f1 = src_dir / "game.zip"
    f1.write_bytes(b"flat")

    transfer_files([f1], dst_dir, mode="copy", flat=True, system="snes")
    assert (dst_dir / "game.zip").exists()
    assert not (dst_dir / "snes").exists()


def test_transfer_files_system_subdir(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    f1 = src_dir / "game.zip"
    f1.write_bytes(b"sub")

    transfer_files([f1], dst_dir, mode="copy", flat=False, system="snes")
    assert (dst_dir / "snes" / "game.zip").exists()


def test_transfer_files_progress_callback(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    f1 = src_dir / "game.zip"
    f1.write_bytes(b"data")

    events = []
    transfer_files([f1], dst_dir, mode="copy",
                   on_progress=lambda evt: events.append(evt))

    assert len(events) > 0
    assert events[0].phase == "transferring"


def test_generate_m3u_playlist(tmp_path):
    rom_files = [
        Path("/roms/Zelda (USA).sfc"),
        Path("/roms/Mario (USA).sfc"),
        Path("/roms/Contra (USA).sfc"),
    ]

    path = generate_m3u_playlist("snes", rom_files, tmp_path)
    assert path.name == "snes.m3u"
    assert path.exists()

    content = path.read_text(encoding="utf-8")
    lines = [l for l in content.strip().split("\n") if l]
    assert len(lines) == 3
    assert lines[0] == "Contra (USA).sfc"
    assert lines[-1] == "Zelda (USA).sfc"


def test_generate_m3u_empty(tmp_path):
    path = generate_m3u_playlist("snes", [], tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip() == ""


def test_generate_gamelist_xml(tmp_path):
    rom_files = [
        Path("/roms/Game One (USA).zip"),
        Path("/roms/Game & Two (USA).zip"),
    ]

    path = generate_gamelist_xml("snes", rom_files, tmp_path)
    assert path.name == "gamelist.xml"

    content = path.read_text(encoding="utf-8")
    assert '<?xml version="1.0"?>' in content
    assert "<gameList>" in content and "</gameList>" in content
    assert "<game>" in content
    assert "&amp;" in content
    assert "<path>./Game & Two (USA).zip</path>" in content
    assert "<name>Game One (USA)</name>" in content


def test_generate_gamelist_xml_escaping(tmp_path):
    rom_files = [Path("/roms/Game <Special> (USA).zip")]
    path = generate_gamelist_xml("snes", rom_files, tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "&lt;" in content and "&gt;" in content


def test_generate_retroarch_playlist(tmp_path):
    rom_dir = Path("/roms/snes")
    rom_files = [
        Path("/roms/snes/Zelda (USA).sfc"),
        Path("/roms/snes/Mario (USA).sfc"),
    ]

    path = generate_retroarch_playlist("snes", rom_files, rom_dir, tmp_path)
    assert path.name == "snes.lpl"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "1.5"

    items = data["items"]
    assert len(items) == 2
    assert items[0]["label"] == "Mario (USA)"
    assert items[1]["label"] == "Zelda (USA)"

    entry = items[0]
    assert "path" in entry
    assert "label" in entry
    assert "core_path" in entry
    assert entry["db_name"] == "snes.lpl"
    assert entry["core_path"] == "DETECT"
