"""Tests for retro_refiner.systems module."""
from pathlib import Path

from retro_refiner.systems import load_system_data, reset_cache, SystemData


# =============================================================================
# SystemData Tests
# =============================================================================

def test_load_returns_system_data():
    reset_cache()
    data = load_system_data()
    assert isinstance(data, SystemData)


def test_known_systems_count():
    reset_cache()
    data = load_system_data()
    assert len(data.known_systems) > 100


def test_known_systems_includes_nes():
    data = load_system_data()
    assert 'nes' in data.known_systems


def test_known_systems_includes_snes():
    data = load_system_data()
    assert 'snes' in data.known_systems


def test_known_systems_includes_mame():
    data = load_system_data()
    assert 'mame' in data.known_systems


def test_extension_nes():
    data = load_system_data()
    assert data.extension_to_system.get('.nes') == 'nes'


def test_extension_sfc():
    data = load_system_data()
    assert data.extension_to_system.get('.sfc') == 'snes'


def test_extension_md():
    data = load_system_data()
    assert data.extension_to_system.get('.md') == 'genesis'


def test_alias_super_nintendo():
    data = load_system_data()
    assert data.folder_aliases.get('super-nintendo') == 'snes'


def test_alias_megadrive():
    data = load_system_data()
    assert data.folder_aliases.get('megadrive') == 'genesis'


def test_libretro_dat_systems_contains_nes():
    data = load_system_data()
    assert 'nes' in data.libretro_dat_systems


def test_redump_dat_systems_contains_psx():
    data = load_system_data()
    assert 'psx' in data.redump_dat_systems


def test_launchbox_platform_map_populated():
    data = load_system_data()
    assert len(data.launchbox_platform_map) > 0


def test_dat_name_to_system_populated():
    data = load_system_data()
    assert len(data.dat_name_to_system) > 0


def test_system_to_launchbox_populated():
    data = load_system_data()
    assert len(data.system_to_launchbox) > 0


def test_sorted_dat_names_longest_first():
    data = load_system_data()
    names = [k for k, _ in data.sorted_dat_names]
    assert names == sorted(names, key=len, reverse=True)


def test_sorted_aliases_longest_first():
    data = load_system_data()
    aliases = [k for k, _ in data.sorted_aliases]
    assert aliases == sorted(aliases, key=len, reverse=True)


# =============================================================================
# Caching Tests
# =============================================================================

def test_caching_returns_same_object():
    reset_cache()
    first = load_system_data()
    second = load_system_data()
    assert first is second


# =============================================================================
# Custom Path Tests
# =============================================================================

def test_load_with_explicit_path():
    project_root = Path(__file__).resolve().parent.parent
    systems_json = project_root / 'data' / 'systems.json'

    reset_cache()
    data = load_system_data(systems_json_path=systems_json)
    assert isinstance(data, SystemData)
    assert len(data.known_systems) > 100
