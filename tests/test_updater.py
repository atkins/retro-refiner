"""Tests for retro_refiner.updater module."""
from datetime import datetime, timezone
from unittest.mock import patch

from retro_refiner.updater import (
    get_current_version, is_newer, is_valid_version,
    _normalize_version, can_check_for_updates, should_check,
    load_update_state, save_update_state,
    get_asset_url, get_asset_size,
)


# -- Version comparison --

class TestVersionComparison:
    def test_newer_version(self):
        assert is_newer('v2026.03.25.1000', 'v2026.03.24.1330')

    def test_same_version(self):
        assert not is_newer('v2026.03.24.1330', 'v2026.03.24.1330')

    def test_older_version(self):
        assert not is_newer('v2026.03.23.0900', 'v2026.03.24.1330')

    def test_invalid_remote(self):
        assert not is_newer('invalid', 'v2026.03.24.1330')

    def test_invalid_local(self):
        assert not is_newer('v2026.03.25.1000', 'dev')

    def test_both_invalid(self):
        assert not is_newer('bad', 'dev')

    def test_strip_v_prefix(self):
        assert _normalize_version('v2026.03.24.1330') == '2026.03.24.1330'

    def test_no_prefix(self):
        assert _normalize_version('2026.03.24.1330') == '2026.03.24.1330'

    def test_valid_format(self):
        assert is_valid_version('v2026.03.24.1330')
        assert is_valid_version('2026.03.24.1330')

    def test_invalid_format(self):
        assert not is_valid_version('dev')
        assert not is_valid_version('v2')
        assert not is_valid_version('2026.03.24')
        assert not is_valid_version('')


# -- can_check_for_updates --

class TestCanCheck:
    def test_dev_version_skips(self):
        with patch('retro_refiner.updater.__version__', 'dev'):
            assert not can_check_for_updates()

    def test_not_frozen_skips(self):
        with patch('retro_refiner.updater.__version__', '2026.03.24.1330'), \
             patch('retro_refiner.updater.is_frozen', return_value=False):
            assert not can_check_for_updates()

    def test_frozen_with_version_proceeds(self):
        with patch('retro_refiner.updater.__version__', '2026.03.24.1330'), \
             patch('retro_refiner.updater.is_frozen', return_value=True):
            assert can_check_for_updates()


# -- Rate limiting --

class TestShouldCheck:
    def test_no_state(self):
        assert should_check({})

    def test_no_last_check(self):
        assert should_check({'last_check': None})

    def test_old_check(self):
        assert should_check({'last_check': '2020-01-01T00:00:00'})

    def test_recent_check(self):
        now = datetime.now(timezone.utc).isoformat()
        assert not should_check({'last_check': now})

    def test_invalid_timestamp(self):
        assert should_check({'last_check': 'not-a-date'})


# -- State persistence --

class TestStatePersistence:
    def test_save_and_load(self, tmp_path):
        with patch('retro_refiner.updater._state_path',
                   return_value=tmp_path / '_update_state.json'):
            save_update_state({'last_check': '2026-03-25T10:00:00'})
            state = load_update_state()
            assert state['last_check'] == '2026-03-25T10:00:00'

    def test_load_missing_file(self, tmp_path):
        with patch('retro_refiner.updater._state_path',
                   return_value=tmp_path / 'nonexistent.json'):
            assert load_update_state() == {}

    def test_load_corrupt_file(self, tmp_path):
        bad = tmp_path / 'bad.json'
        bad.write_text('not json', encoding='utf-8')
        with patch('retro_refiner.updater._state_path',
                   return_value=bad):
            assert load_update_state() == {}


# -- Asset selection --

MOCK_RELEASE = {
    'tag_name': 'v2026.03.25.1000',
    'html_url': 'https://github.com/atkins/retro-refiner/releases/tag/v2026.03.25.1000',
    'assets': [
        {'name': 'retro-refiner-windows.exe',
         'browser_download_url': 'https://github.com/.../retro-refiner-windows.exe',
         'size': 50_000_000},
        {'name': 'retro-refiner-macos',
         'browser_download_url': 'https://github.com/.../retro-refiner-macos',
         'size': 48_000_000},
        {'name': 'retro-refiner-linux',
         'browser_download_url': 'https://github.com/.../retro-refiner-linux',
         'size': 45_000_000},
    ],
}


class TestAssetSelection:
    def test_windows_asset(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'win32'
            url = get_asset_url(MOCK_RELEASE)
            assert 'windows.exe' in url

    def test_macos_asset(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'darwin'
            url = get_asset_url(MOCK_RELEASE)
            assert 'macos' in url

    def test_linux_asset(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'linux'
            url = get_asset_url(MOCK_RELEASE)
            assert 'linux' in url

    def test_unknown_platform(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'freebsd'
            assert get_asset_url(MOCK_RELEASE) is None

    def test_asset_size(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'win32'
            assert get_asset_size(MOCK_RELEASE) == 50_000_000

    def test_no_assets(self):
        assert get_asset_url({'assets': []}) is None
        assert get_asset_size({'assets': []}) == 0
