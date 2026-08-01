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


def test_transfer_files_relpaths_preserve_subdirs(tmp_path):
    """Same basename in different subdirs must not collide (data loss)."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    (src_dir / "usa").mkdir(parents=True)
    (src_dir / "japan").mkdir(parents=True)
    dst_dir.mkdir()

    f_usa = src_dir / "usa" / "game.zip"
    f_jpn = src_dir / "japan" / "game.zip"
    f_usa.write_bytes(b"usa_content")
    f_jpn.write_bytes(b"japan_content")

    relpaths = {
        str(f_usa): "usa/game.zip",
        str(f_jpn): "japan/game.zip",
    }

    stats = transfer_files([f_usa, f_jpn], dst_dir, mode="copy",
                           flat=False, system="snes", relpaths=relpaths)

    assert stats["transferred"] == 2
    assert stats["skipped"] == 0
    assert stats["errors"] == 0

    out_usa = dst_dir / "snes" / "usa" / "game.zip"
    out_jpn = dst_dir / "snes" / "japan" / "game.zip"
    assert out_usa.exists()
    assert out_jpn.exists()
    assert out_usa.read_bytes() == b"usa_content"
    assert out_jpn.read_bytes() == b"japan_content"


@pytest.mark.parametrize("relpaths", [None, {}])
def test_transfer_files_relpaths_fallback_to_name(tmp_path, relpaths):
    """Omitted/empty relpaths keeps the pre-fix basename behaviour."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    (src_dir / "sub").mkdir(parents=True)
    dst_dir.mkdir()

    f1 = src_dir / "sub" / "game.zip"
    f1.write_bytes(b"fallback")

    stats = transfer_files([f1], dst_dir, mode="copy", flat=False,
                           system="snes", relpaths=relpaths)

    assert stats["transferred"] == 1
    assert stats["skipped"] == 0
    assert (dst_dir / "snes" / "game.zip").read_bytes() == b"fallback"
    assert not (dst_dir / "snes" / "sub").exists()


def test_transfer_files_relpaths_partial_map_falls_back(tmp_path):
    """Sources missing from the map still land on their basename."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    (src_dir / "usa").mkdir(parents=True)
    dst_dir.mkdir()

    mapped = src_dir / "usa" / "mapped.zip"
    unmapped = src_dir / "usa" / "unmapped.zip"
    mapped.write_bytes(b"m")
    unmapped.write_bytes(b"u")

    stats = transfer_files([mapped, unmapped], dst_dir, mode="copy",
                           flat=False, system="snes",
                           relpaths={str(mapped): "usa/mapped.zip"})

    assert stats["transferred"] == 2
    assert (dst_dir / "snes" / "usa" / "mapped.zip").exists()
    assert (dst_dir / "snes" / "unmapped.zip").exists()


def test_transfer_files_relpaths_skips_existing_at_relpath(tmp_path):
    """Skip detection uses the relative destination, not the basename."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    (src_dir / "usa").mkdir(parents=True)
    (dst_dir / "snes" / "usa").mkdir(parents=True)

    f1 = src_dir / "usa" / "game.zip"
    f1.write_bytes(b"new_content")
    (dst_dir / "snes" / "usa" / "game.zip").write_bytes(b"old_content")

    stats = transfer_files([f1], dst_dir, mode="copy", flat=False,
                           system="snes",
                           relpaths={str(f1): "usa/game.zip"})

    assert stats["skipped"] == 1
    assert stats["transferred"] == 0
    assert ((dst_dir / "snes" / "usa" / "game.zip").read_bytes()
            == b"old_content")


def test_transfer_files_relpaths_move_mode_preserves_subdirs(tmp_path):
    """Move mode also creates missing intermediate directories."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    (src_dir / "disc1").mkdir(parents=True)
    (src_dir / "disc2").mkdir(parents=True)
    dst_dir.mkdir()

    f1 = src_dir / "disc1" / "game.bin"
    f2 = src_dir / "disc2" / "game.bin"
    f1.write_bytes(b"one")
    f2.write_bytes(b"two")

    relpaths = {str(f1): "disc1/game.bin", str(f2): "disc2/game.bin"}
    stats = transfer_files([f1, f2], dst_dir, mode="move", flat=False,
                           system="psx", relpaths=relpaths)

    assert stats["transferred"] == 2
    assert stats["skipped"] == 0
    assert not f1.exists()
    assert not f2.exists()
    assert (dst_dir / "psx" / "disc1" / "game.bin").read_bytes() == b"one"
    assert (dst_dir / "psx" / "disc2" / "game.bin").read_bytes() == b"two"


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


# =============================================================================
# clean_destination: recursive and relpath-aware
# =============================================================================
# A recursive scan writes ROMs into subdirectories, so a top-level-only
# pass never saw them, and a basename-keyed keep set did not match the
# relative paths the commit actually writes.

class TestCleanDestinationRecursive:

    @staticmethod
    def _tree(dest):
        sysdir = dest / 'snes'
        (sysdir / 'usa').mkdir(parents=True)
        (sysdir / 'japan').mkdir(parents=True)
        (sysdir / 'usa' / 'game.zip').write_bytes(b'a')
        (sysdir / 'japan' / 'game.zip').write_bytes(b'b')
        (sysdir / 'orphan.zip').write_bytes(b'c')
        return sysdir

    def test_keeps_nested_files_listed_by_relpath(self, tmp_path):
        sysdir = self._tree(tmp_path)
        stats = clean_destination(
            tmp_path, 'snes', False,
            {'usa/game.zip', 'japan/game.zip'})
        assert stats['removed'] == 1          # only orphan.zip
        assert (sysdir / 'usa' / 'game.zip').exists()
        assert (sysdir / 'japan' / 'game.zip').exists()
        assert not (sysdir / 'orphan.zip').exists()

    def test_removes_nested_file_not_in_keep_set(self, tmp_path):
        sysdir = self._tree(tmp_path)
        clean_destination(tmp_path, 'snes', False,
                          {'usa/game.zip', 'orphan.zip'})
        assert (sysdir / 'usa' / 'game.zip').exists()
        assert not (sysdir / 'japan' / 'game.zip').exists()

    def test_bare_filenames_still_honoured_for_flat_layout(self, tmp_path):
        (tmp_path / 'a.zip').write_bytes(b'a')
        (tmp_path / 'b.zip').write_bytes(b'b')
        stats = clean_destination(tmp_path, None, True, {'a.zip'})
        assert stats['removed'] == 1
        assert (tmp_path / 'a.zip').exists()
        assert not (tmp_path / 'b.zip').exists()

    def test_generated_outputs_are_not_deleted(self, tmp_path):
        sysdir = tmp_path / 'snes'
        sysdir.mkdir(parents=True)
        (sysdir / 'game.zip').write_bytes(b'a')
        (sysdir / 'playlist.m3u').write_text('x', encoding='utf-8')
        (sysdir / 'gamelist.xml').write_text('x', encoding='utf-8')
        clean_destination(tmp_path, 'snes', False, {'game.zip'})
        assert (sysdir / 'playlist.m3u').exists()
        assert (sysdir / 'gamelist.xml').exists()

    def test_emptied_directories_are_pruned(self, tmp_path):
        sysdir = self._tree(tmp_path)
        clean_destination(tmp_path, 'snes', False, {'usa/game.zip'})
        assert not (sysdir / 'japan').exists()
        assert (sysdir / 'usa').exists()

    def test_missing_target_is_a_noop(self, tmp_path):
        stats = clean_destination(tmp_path, 'nope', False, set())
        assert stats == {'removed': 0, 'errors': 0}


# =============================================================================
# Playlist entries keep subdirectory structure
# =============================================================================
# A recursive scan writes ROMs into subdirectories; a bare basename is
# both ambiguous and unresolvable by the emulator.

def test_m3u_entries_are_relative_to_rom_dir(tmp_path):
    (tmp_path / 'usa').mkdir()
    (tmp_path / 'japan').mkdir()
    roms = [tmp_path / 'usa' / 'game.zip',
            tmp_path / 'japan' / 'game.zip']
    for r in roms:
        r.write_bytes(b'x')
    path = generate_m3u_playlist('snes', roms, tmp_path)
    lines = sorted(l for l in path.read_text(encoding='utf-8').split('\n')
                   if l)
    assert lines == ['japan/game.zip', 'usa/game.zip']


def test_m3u_falls_back_to_name_outside_rom_dir(tmp_path):
    path = generate_m3u_playlist('snes', [Path('/elsewhere/a.zip')],
                                 tmp_path)
    assert path.read_text(encoding='utf-8').strip() == 'a.zip'


def test_gamelist_paths_are_relative_when_rom_dir_given(tmp_path):
    rom_dir = tmp_path / 'roms'
    (rom_dir / 'usa').mkdir(parents=True)
    rom = rom_dir / 'usa' / 'game.zip'
    rom.write_bytes(b'x')
    out = tmp_path / 'out'
    out.mkdir()
    path = generate_gamelist_xml('snes', [rom], out, rom_dir=rom_dir)
    assert '<path>./usa/game.zip</path>' in path.read_text(encoding='utf-8')


def test_gamelist_without_rom_dir_uses_basename(tmp_path):
    path = generate_gamelist_xml('snes', [Path('/roms/usa/game.zip')],
                                 tmp_path)
    assert '<path>./game.zip</path>' in path.read_text(encoding='utf-8')


def test_retroarch_paths_keep_subdirectory(tmp_path):
    rom_dir = tmp_path / 'roms'
    (rom_dir / 'usa').mkdir(parents=True)
    rom = rom_dir / 'usa' / 'game.zip'
    rom.write_bytes(b'x')
    path = generate_retroarch_playlist('snes', [rom], rom_dir, tmp_path)
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['items'][0]['path'] == str(rom)
