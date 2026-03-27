"""Tests for retro_refiner v2 wrapper modules."""
import importlib
from pathlib import Path

import pytest

from retro_refiner.systems import load_system_data, SystemData
from retro_refiner.models import (
    ProgressEvent, ExcludedRom, FilterStats, FilterResult,
    ScanResult, SystemScanInfo,
)
from retro_refiner.network import is_url, is_archive_org_url
from retro_refiner.scanner import (
    detect_system_from_path, get_system_scan_info, scan_local_sources,
)
from retro_refiner.filter import parse_rom_filename, filter_network_roms
from retro_refiner.dat import normalize_title
from retro_refiner.config import Config
from retro_refiner.mame import (
    filter_mame_network_roms, should_include_mame_game, MameGameInfo,
)
from retro_refiner.teknoparrot import (
    filter_teknoparrot_network_roms, parse_teknoparrot_filename,
)
from retro_refiner.transfer import transfer_files
from retro_refiner.ui.api import _parse_size_string
from retro_refiner.ratings import (
    combine_ratings, boost_exclusive_ratings,
    resolve_top_n, apply_top_n_filter, apply_size_budget,
)
from retro_refiner.dedup import parse_pc_game_list
from retro_refiner.dat import normalize_title_for_dedupe
from retro_refiner.cli import _parse_size_string as cli_parse_size_string


# =============================================================================
# Module Import Tests
# =============================================================================

@pytest.mark.parametrize("module", [
    "models",
    "paths",
    "systems",
    "network",
    "scanner",
    "dat",
    "filter",
    "mame",
    "teknoparrot",
    "downloader",
    "transfer",
    "config",
    "updater",
    "log",
])
def test_module_importable(module):
    """Verify each v2 module imports without error."""
    importlib.import_module(f"retro_refiner.{module}")


# =============================================================================
# Systems Module Tests
# =============================================================================

def test_load_system_data_returns_system_data():
    sysdata = load_system_data()
    assert isinstance(sysdata, SystemData)


def test_system_data_has_many_systems():
    sysdata = load_system_data()
    assert len(sysdata.known_systems) > 100


def test_extension_to_system_has_sfc():
    sysdata = load_system_data()
    assert '.sfc' in sysdata.extension_to_system


def test_folder_aliases_has_super_nintendo():
    sysdata = load_system_data()
    assert 'super-nintendo' in sysdata.folder_aliases


# =============================================================================
# Models Tests
# =============================================================================

def test_progress_event_construction():
    evt = ProgressEvent(phase="scanning", message="test", current=5, total=10)
    assert evt.phase == "scanning"
    assert evt.current == 5
    assert evt.total == 10


def test_progress_event_defaults():
    evt = ProgressEvent(phase="complete")
    assert evt.message == ""
    assert evt.current == 0
    assert evt.system == ""


def test_excluded_rom_construction():
    exc = ExcludedRom(filename="test.rom", reason="beta", size=1024)
    assert exc.filename == "test.rom"
    assert exc.reason == "beta"


def test_filter_stats_construction():
    stats = FilterStats(source_count=100, selected_count=50)
    assert stats.source_count == 100
    assert stats.filter_breakdown == {}


def test_filter_result_construction():
    fr = FilterResult(system="snes")
    assert fr.system == "snes"
    assert fr.selected == []
    assert fr.excluded == []


def test_scan_result_default_construction():
    sr = ScanResult()
    assert sr.url_dict == {}
    assert sr.url_sizes == {}


def test_scan_result_with_data():
    sr = ScanResult(url_dict={"snes": ["url1"]}, url_sizes={"url1": 1000})
    assert sr.url_dict["snes"] == ["url1"]
    assert sr.url_sizes["url1"] == 1000


def test_system_scan_info_construction():
    info = SystemScanInfo(system="genesis", file_count=42,
                          total_size=1048576, source_type="local")
    assert info.system == "genesis"
    assert info.file_count == 42


# =============================================================================
# Network Module Tests
# =============================================================================

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/roms", True),
    ("http://example.com/roms", True),
    ("/home/user/roms", False),
    ("C:\\Users\\roms", False),
])
def test_is_url(url, expected):
    assert is_url(url) == expected


def test_is_archive_org_url_true():
    assert is_archive_org_url("https://archive.org/download/something")


def test_is_archive_org_url_false():
    assert not is_archive_org_url("https://example.com/roms")


# =============================================================================
# Scanner Module Tests
# =============================================================================

def test_detect_system_from_path_mame():
    assert detect_system_from_path("/roms/MAME/") == "mame"


def test_detect_system_from_path_snes():
    result = detect_system_from_path("https://example.com/roms/Super Nintendo/")
    assert result == "snes"


def test_get_system_scan_info_count():
    test_dict = {"snes": ["a.sfc", "b.sfc"], "genesis": ["c.md"]}
    info_list = get_system_scan_info(test_dict, source_type="network")
    assert len(info_list) == 2


def test_get_system_scan_info_type():
    test_dict = {"snes": ["a.sfc", "b.sfc"], "genesis": ["c.md"]}
    info_list = get_system_scan_info(test_dict, source_type="network")
    assert all(isinstance(i, SystemScanInfo) for i in info_list)


def test_get_system_scan_info_file_counts():
    test_dict = {"snes": ["a.sfc", "b.sfc"], "genesis": ["c.md"]}
    info_list = get_system_scan_info(test_dict, source_type="network")
    info_by_system = {i.system: i for i in info_list}
    assert info_by_system["snes"].file_count == 2


def test_scan_local_sources_detects_snes(tmp_path):
    snes_dir = tmp_path / 'snes'
    snes_dir.mkdir()
    (snes_dir / 'game1.sfc').write_text('rom1')
    (snes_dir / 'game2.sfc').write_text('rom2')
    (snes_dir / 'readme.txt').write_text('not a rom')

    result = scan_local_sources([tmp_path], recursive=True)
    assert 'snes' in result


def test_scan_local_sources_finds_sfc_files(tmp_path):
    snes_dir = tmp_path / 'snes'
    snes_dir.mkdir()
    (snes_dir / 'game1.sfc').write_text('rom1')
    (snes_dir / 'game2.sfc').write_text('rom2')
    (snes_dir / 'readme.txt').write_text('not a rom')

    result = scan_local_sources([tmp_path], recursive=True)
    assert len(result['snes']) == 2


def test_scan_local_sources_empty_dir(tmp_path):
    result = scan_local_sources([tmp_path])
    assert len(result) == 0


# =============================================================================
# DAT Module Tests
# =============================================================================

def test_parse_rom_filename_base_title():
    info = parse_rom_filename("Super Mario World (USA).sfc")
    assert info.base_title == "Super Mario World"


def test_parse_rom_filename_region():
    info = parse_rom_filename("Super Mario World (USA).sfc")
    assert "USA" in info.region


def test_parse_rom_filename_beta():
    info = parse_rom_filename("Test Game (USA) (Beta).zip")
    assert info.is_beta


def test_normalize_title_returns_nonempty():
    norm = normalize_title("Super Mario World")
    assert isinstance(norm, str)
    assert len(norm) > 0


def test_normalize_title_case_insensitive():
    assert normalize_title("ZELDA") == normalize_title("zelda")


# =============================================================================
# Filter Module Tests
# =============================================================================

def test_filter_network_roms_returns_filter_result():
    config = Config()
    result = filter_network_roms("genesis", [], config)
    assert isinstance(result, FilterResult)
    assert result.system == "genesis"


# =============================================================================
# MAME Module Tests
# =============================================================================

def test_filter_mame_network_roms_empty():
    selected, info = filter_mame_network_roms([], categories={}, games={})
    assert selected == []
    assert info.get('source_size') == 0


def test_should_include_mame_game_maze():
    game = MameGameInfo(
        name='pacman', description='Pac-Man', year='1980',
        manufacturer='Namco', category='Maze', is_parent=True,
        parent_name='', is_bios=False, is_device=False,
        has_chd=False, chd_names=[], region='USA',
    )
    include, _ = should_include_mame_game(game, 'Maze')
    assert include


# =============================================================================
# TeknoParrot Module Tests
# =============================================================================

def test_filter_teknoparrot_network_roms_empty():
    selected, info = filter_teknoparrot_network_roms([])
    assert selected == []
    assert info.get('source_size') == 0


def test_parse_teknoparrot_filename():
    info = parse_teknoparrot_filename(
        "House of the Dead 4 (1.00) [Sega Lindbergh] [TP].zip")
    assert info is not None
    assert info.base_title


# =============================================================================
# Transfer Module Tests
# =============================================================================

def test_transfer_files_returns_result_dict():
    result = transfer_files([], Path("/tmp/test"))
    assert isinstance(result, dict)
    assert 'transferred' in result


def test_transfer_files_empty_list_zeros():
    result = transfer_files([], Path("/tmp/test"))
    assert result['transferred'] == 0
    assert result['errors'] == 0


def test_transfer_files_copy(tmp_path):
    src_dir = tmp_path / 'src'
    src_dir.mkdir()
    test_file = src_dir / 'game.sfc'
    test_file.write_text('rom data')

    dst_dir = tmp_path / 'dst'
    result = transfer_files([test_file], dst_dir, mode='copy', system='snes')
    assert result['transferred'] == 1


def test_transfer_files_creates_system_subdir(tmp_path):
    src_dir = tmp_path / 'src'
    src_dir.mkdir()
    test_file = src_dir / 'game.sfc'
    test_file.write_text('rom data')

    dst_dir = tmp_path / 'dst'
    transfer_files([test_file], dst_dir, mode='copy', system='snes')
    assert (dst_dir / 'snes' / 'game.sfc').exists()


def test_transfer_files_skips_existing(tmp_path):
    src_dir = tmp_path / 'src'
    src_dir.mkdir()
    test_file = src_dir / 'game.sfc'
    test_file.write_text('rom data')

    dst_dir = tmp_path / 'dst'
    transfer_files([test_file], dst_dir, mode='copy', system='snes')
    result2 = transfer_files([test_file], dst_dir, mode='copy', system='snes')
    assert result2['skipped'] == 1


def test_transfer_files_flat_mode(tmp_path):
    src_dir = tmp_path / 'src'
    src_dir.mkdir()
    test_file = src_dir / 'game.sfc'
    test_file.write_text('rom data')

    flat_dir = tmp_path / 'flat'
    transfer_files([test_file], flat_dir, mode='copy', flat=True)
    assert (flat_dir / 'game.sfc').exists()


# =============================================================================
# Budget Filter Tests (API)
# =============================================================================

@pytest.mark.parametrize("input_str,expected", [
    ('10GB', 10 * 1024 ** 3),
    ('500MB', 500 * 1024 ** 2),
    ('1.5GB', int(1.5 * 1024 ** 3)),
    (None, None),
    ('', None),
    ('invalid', None),
])
def test_parse_size_string(input_str, expected):
    assert _parse_size_string(input_str) == expected


# =============================================================================
# Ratings Function Tests
# =============================================================================

def test_resolve_top_n_integer():
    assert resolve_top_n(10, 100) == 10


def test_resolve_top_n_percentage():
    assert resolve_top_n("25%", 100) == 25


def test_resolve_top_n_none():
    assert resolve_top_n(None, 100) is None


def test_combine_ratings_weighted_average():
    igdb = {'snes': {'mario': {'rating': 8.0, 'votes': 100, 'name': 'Mario'}}}
    lb = {'snes': {'mario': {'rating': 9.0, 'votes': 200, 'name': 'Mario'}}}
    combined = combine_ratings(igdb, lb)
    assert 'snes' in combined
    assert 'mario' in combined['snes']
    rating = combined['snes']['mario']['rating']
    assert abs(rating - 8.67) < 0.01


def test_boost_exclusive_ratings():
    ratings = {
        'snes': {'mario': {'rating': 8.0, 'votes': 100, 'name': 'Mario'},
                 'zelda': {'rating': 9.0, 'votes': 50, 'name': 'Zelda'}},
        'genesis': {'sonic': {'rating': 8.5, 'votes': 80, 'name': 'Sonic'},
                    'zelda': {'rating': 7.0, 'votes': 40, 'name': 'Zelda'}},
    }
    boosted = boost_exclusive_ratings(ratings, boost=1.0)
    assert boosted['snes']['mario']['rating'] == 9.0
    assert boosted['snes']['zelda']['rating'] == 9.0


def test_apply_top_n_filter():
    roms = [parse_rom_filename(n) for n in
            ['Game A (USA).sfc', 'Game B (USA).sfc', 'Game C (USA).sfc']]
    sys_ratings = {
        'game a': {'rating': 9.0, 'votes': 100},
        'game b': {'rating': 7.0, 'votes': 50},
        'game c': {'rating': 5.0, 'votes': 30},
    }
    filtered = apply_top_n_filter(roms, sys_ratings, 2)
    assert len(filtered) == 2


def test_apply_size_budget_fits():
    items = ['a', 'b', 'c']
    sizes = {'a': 100, 'b': 200, 'c': 300}
    kept, used = apply_size_budget(items, sizes, 350)
    assert len(kept) == 2
    assert used == 300


def test_apply_size_budget_zero():
    items = ['a', 'b', 'c']
    sizes = {'a': 100, 'b': 200, 'c': 300}
    kept, used = apply_size_budget(items, sizes, 0)
    assert len(kept) == 0
    assert used == 0


# =============================================================================
# CLI Budget Helper Tests
# =============================================================================

@pytest.mark.parametrize("input_str,expected", [
    ('10GB', 10 * 1024 ** 3),
    ('1TB', 1024 ** 4),
    ('abc', None),
])
def test_cli_parse_size_string(input_str, expected):
    assert cli_parse_size_string(input_str) == expected


# =============================================================================
# Dedup Function Tests
# =============================================================================

def test_normalize_title_for_dedupe_nonempty():
    norm = normalize_title_for_dedupe("Super Mario World")
    assert isinstance(norm, str)
    assert len(norm) > 0


def test_parse_pc_game_list_missing_file():
    titles = parse_pc_game_list("/nonexistent/file.xml")
    assert titles == set()
