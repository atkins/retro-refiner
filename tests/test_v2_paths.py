"""Tests for retro_refiner.paths module."""
from pathlib import Path

from retro_refiner.paths import get_base_path, get_runtime_path


def test_get_base_path_returns_existing_path():
    result = get_base_path()
    assert isinstance(result, Path)
    assert result.exists()


def test_get_runtime_path_returns_existing_path():
    result = get_runtime_path()
    assert isinstance(result, Path)
    assert result.exists()


def test_base_path_contains_systems_json():
    base = get_base_path()
    systems_json = base / 'data' / 'systems.json'
    assert systems_json.exists()
