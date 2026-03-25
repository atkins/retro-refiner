"""Tests for scanner.py module.

Covers system detection, local scanning, and ScanProgressBar.
"""

import os
import sys
from pathlib import Path

import pytest

from retro_refiner.scanner import (
    detect_system_from_path,
    scan_local_sources,
    get_system_scan_info,
    ScanProgressBar,
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
