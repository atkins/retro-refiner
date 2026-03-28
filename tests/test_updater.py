"""Tests for retro_refiner.updater module."""
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import httpx

from retro_refiner.updater import (
    get_current_version, is_newer, is_valid_version,
    _normalize_version, can_check_for_updates, should_check,
    load_update_state, save_update_state,
    get_asset_url, get_asset_size,
    check_for_update, download_update, apply_update,
    startup_recovery, launch_and_exit,
    ASSET_NAMES, GITHUB_API_URL,
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
        {'name': 'retro-refiner.exe',
         'browser_download_url': 'https://github.com/.../retro-refiner.exe',
         'size': 50_000_000},
        {'name': 'retro-refiner-macos.zip',
         'browser_download_url': 'https://github.com/.../retro-refiner-macos.zip',
         'size': 48_000_000},
        {'name': 'retro-refiner',
         'browser_download_url': 'https://github.com/.../retro-refiner',
         'size': 45_000_000},
    ],
}


class TestAssetSelection:
    def test_windows_asset(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'win32'
            url = get_asset_url(MOCK_RELEASE)
            assert 'retro-refiner.exe' in url

    def test_macos_asset(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'darwin'
            url = get_asset_url(MOCK_RELEASE)
            assert 'macos.zip' in url

    def test_linux_asset(self):
        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'linux'
            url = get_asset_url(MOCK_RELEASE)
            assert 'retro-refiner' in url

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


# -- check_for_update --

class TestCheckForUpdate:
    def test_returns_info_when_newer(self):
        def handler(request):
            return httpx.Response(200, json={
                'tag_name': 'v9999.12.31.2359',
                'html_url': 'https://github.com/atkins/retro-refiner/releases/tag/v9999.12.31.2359',
                'assets': [{
                    'name': ASSET_NAMES.get(sys.platform, 'retro-refiner-linux'),
                    'browser_download_url': 'https://example.com/download',
                    'size': 1000,
                }],
            })

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('retro_refiner.updater.__version__', '2026.03.24.1330'), \
             patch.object(httpx, 'Client', return_value=client):
            result = check_for_update()
            assert result is not None
            assert result['version'] == 'v9999.12.31.2359'
            assert result['url'] == 'https://example.com/download'
            assert result['size'] == 1000

    def test_returns_none_when_same_version(self):
        def handler(request):
            return httpx.Response(200, json={
                'tag_name': 'v2026.03.24.1330',
                'assets': [],
            })
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('retro_refiner.updater.__version__', '2026.03.24.1330'), \
             patch.object(httpx, 'Client', return_value=client):
            result = check_for_update()
            assert result is None

    def test_returns_none_on_error(self):
        """Network errors should return None silently."""
        def handler(request):
            return httpx.Response(500)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('retro_refiner.updater.__version__', '2026.03.24.1330'), \
             patch.object(httpx, 'Client', return_value=client):
            result = check_for_update()
            assert result is None


# -- apply_update --

class TestApplyUpdate:
    def test_apply_linux(self, tmp_path):
        exe = tmp_path / 'app'
        exe.write_bytes(b'old binary')
        new = tmp_path / 'app_new'
        new.write_bytes(b'new binary')

        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'linux'
            result = apply_update(new, exe)
        assert result is True
        assert exe.read_bytes() == b'new binary'

    def test_apply_windows_creates_old(self, tmp_path):
        exe = tmp_path / 'app.exe'
        exe.write_bytes(b'old binary')
        new = tmp_path / 'app_new.exe'
        new.write_bytes(b'new binary')
        old = tmp_path / 'app.exe.old'

        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'win32'
            result = apply_update(new, exe)
        assert result is True
        assert exe.read_bytes() == b'new binary'
        assert old.read_bytes() == b'old binary'

    def test_apply_failure_returns_false(self, tmp_path):
        exe = tmp_path / 'nonexistent'
        new = tmp_path / 'also_nonexistent'

        with patch('retro_refiner.updater.sys') as mock_sys:
            mock_sys.platform = 'linux'
            result = apply_update(new, exe)
        assert result is False


# -- startup_recovery --

class TestStartupRecovery:
    def test_recovery_when_exe_missing(self, tmp_path):
        exe = tmp_path / 'app.exe'
        old = tmp_path / 'app.exe.old'
        old.write_bytes(b'old binary')

        with patch('retro_refiner.updater.is_frozen', return_value=True):
            startup_recovery(exe)
        assert exe.exists()
        assert exe.read_bytes() == b'old binary'
        assert not old.exists()

    def test_cleanup_old_when_both_exist(self, tmp_path):
        exe = tmp_path / 'app.exe'
        exe.write_bytes(b'new binary')
        old = tmp_path / 'app.exe.old'
        old.write_bytes(b'old binary')

        with patch('retro_refiner.updater.is_frozen', return_value=True):
            startup_recovery(exe)
        assert exe.exists()
        assert not old.exists()

    def test_noop_when_not_frozen(self, tmp_path):
        old = tmp_path / 'app.exe.old'
        old.write_bytes(b'old binary')

        with patch('retro_refiner.updater.is_frozen', return_value=False):
            startup_recovery(tmp_path / 'app.exe')
        assert old.exists()

    def test_noop_when_no_old(self, tmp_path):
        exe = tmp_path / 'app.exe'
        exe.write_bytes(b'binary')

        with patch('retro_refiner.updater.is_frozen', return_value=True):
            startup_recovery(exe)
        assert exe.exists()


# -- download verification --

class TestDownloadUpdate:
    def test_size_mismatch_returns_none(self, tmp_path):
        def handler(request):
            return httpx.Response(200, content=b'small',
                                 headers={'content-length': '5'})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('tempfile.mkdtemp', return_value=str(tmp_path)), \
             patch.object(httpx, 'Client', return_value=client):
            result = download_update('http://example.com/file',
                                     expected_size=999999)
        assert result is None

    def test_successful_download(self, tmp_path):
        content = b'x' * 1000

        def handler(request):
            return httpx.Response(200, content=content,
                                 headers={'content-length': str(len(content))})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('tempfile.mkdtemp', return_value=str(tmp_path)), \
             patch.object(httpx, 'Client', return_value=client):
            result = download_update('http://example.com/file',
                                     expected_size=1000)
        assert result is not None
        assert result.read_bytes() == content

    def test_network_error_returns_none(self, tmp_path):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('tempfile.mkdtemp', return_value=str(tmp_path)), \
             patch.object(httpx, 'Client', return_value=client):
            result = download_update('http://example.com/file',
                                     expected_size=1000)
        assert result is None
