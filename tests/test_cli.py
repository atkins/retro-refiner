"""Tests for retro_refiner.cli module."""
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from retro_refiner.cli import format_size, run_headless
from retro_refiner.config import Config, load_config, save_config


# =============================================================================
# format_size Tests
# =============================================================================

@pytest.mark.parametrize("size,expected", [
    (0, "0 B"),
    (512, "512 B"),
    (1023, "1023 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1024 * 1024, "1.0 MB"),
    (512 * 1024 * 1024, "512.0 MB"),
    (1024 * 1024 * 1024, "1.00 GB"),
    (2 * 1024 * 1024 * 1024, "2.00 GB"),
    (1024 * 1024 * 1024 * 1024, "1.00 TB"),
    (3 * 1024 * 1024 * 1024 * 1024, "3.00 TB"),
])
def test_format_size(size, expected):
    assert format_size(size) == expected


def test_format_size_just_under_1mb():
    size = 1024 * 1024 - 1
    expected = f"{size / 1024:.1f} KB"
    assert format_size(size) == expected


# =============================================================================
# Config Round-Trip Tests
# =============================================================================

class TestConfigRoundTrip:
    """Test that Config exports to YAML and loads back identically."""

    def test_default_english_only(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        original = Config()
        save_config(original, config_path)
        loaded = load_config(config_path)
        assert loaded.selection.english_only == original.selection.english_only

    def test_default_scan_workers(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        original = Config()
        save_config(original, config_path)
        loaded = load_config(config_path)
        assert loaded.network.scan_workers == original.network.scan_workers

    def test_default_no_cache(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        original = Config()
        save_config(original, config_path)
        loaded = load_config(config_path)
        assert loaded.advanced.no_cache == original.advanced.no_cache

    def test_custom_sources(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        custom = Config()
        custom.sources = ['http://example.com/roms', '/path/to/local']
        custom.destination = '/path/to/dest'
        custom.selection.english_only = True
        custom.network.scan_workers = 8
        custom.advanced.no_cache = True

        save_config(custom, config_path)
        loaded = load_config(config_path)
        assert loaded.sources == custom.sources

    def test_custom_destination(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        custom = Config()
        custom.destination = '/path/to/dest'
        save_config(custom, config_path)
        loaded = load_config(config_path)
        assert loaded.destination == custom.destination

    def test_custom_english_only(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        custom = Config()
        custom.selection.english_only = True
        save_config(custom, config_path)
        loaded = load_config(config_path)
        assert loaded.selection.english_only is True

    def test_custom_scan_workers(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        custom = Config()
        custom.network.scan_workers = 8
        save_config(custom, config_path)
        loaded = load_config(config_path)
        assert loaded.network.scan_workers == 8

    def test_custom_no_cache(self, tmp_path):
        config_path = tmp_path / 'test_config.yaml'
        custom = Config()
        custom.advanced.no_cache = True
        save_config(custom, config_path)
        loaded = load_config(config_path)
        assert loaded.advanced.no_cache is True


# =============================================================================
# run_headless --export-config Tests
# =============================================================================

def test_export_config_header():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        run_headless(['--export-config'])
    assert '# Retro-Refiner configuration' in captured.getvalue()


def test_export_config_selection_section():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        run_headless(['--export-config'])
    assert 'selection:' in captured.getvalue()


def test_export_config_network_section():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        run_headless(['--export-config'])
    assert 'network:' in captured.getvalue()


def test_export_config_advanced_section():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        run_headless(['--export-config'])
    assert 'advanced:' in captured.getvalue()


def test_export_config_valid_yaml(tmp_path):
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        run_headless(['--export-config'])

    config_path = tmp_path / 'exported.yaml'
    config_path.write_text(captured.getvalue(), encoding='utf-8')
    loaded = load_config(config_path)
    assert isinstance(loaded, Config)


# =============================================================================
# run_headless Missing Config Tests
# =============================================================================

def test_missing_config_exit_code():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        with pytest.raises(SystemExit) as exc_info:
            run_headless(['--run', '/nonexistent/path/config.yaml'])
    assert exc_info.value.code == 1


def test_missing_config_error_message():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        with pytest.raises(SystemExit):
            run_headless(['--run', '/nonexistent/path/config.yaml'])
    output = captured.getvalue()
    assert 'Error' in output or 'not found' in output


def test_no_args_exit_code():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        with pytest.raises(SystemExit) as exc_info:
            run_headless([])
    assert exc_info.value.code == 1


def test_no_args_usage_message():
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        with pytest.raises(SystemExit):
            run_headless([])
    output = captured.getvalue()
    assert 'Usage' in output or 'usage' in output


# =============================================================================
# Package Export Tests
# =============================================================================

@pytest.mark.parametrize("attr", [
    "__version__",
    "Config",
    "load_config",
    "save_config",
    "load_system_data",
    "SystemData",
])
def test_package_exports(attr):
    import retro_refiner
    assert hasattr(retro_refiner, attr)


def test_package_config_is_usable():
    import retro_refiner
    cfg = retro_refiner.Config()
    assert isinstance(cfg, Config)
