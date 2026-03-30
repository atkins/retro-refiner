"""Tests for transfer.py module.

Covers validate_destination, clean_destination, transfer_files,
and playlist generation (M3U, gamelist XML, RetroArch).
"""

import json
from pathlib import Path

import pytest

from retro_refiner.dat import calculate_crc32
from retro_refiner.transfer import (
    validate_destination,
    clean_destination,
    transfer_files,
    generate_m3u_playlist,
    generate_gamelist_xml,
    generate_retroarch_playlist,
)


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
    assert "<path>./Game &amp; Two (USA).zip</path>" in content
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
