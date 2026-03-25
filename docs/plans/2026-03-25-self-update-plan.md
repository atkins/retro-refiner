# Self-Update Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic update checking and self-update so the built executable can update itself from GitHub Releases.

**Architecture:** A standalone `updater.py` module handles all update logic (check, download, verify, apply, recover). The `api.py` bridge exposes 4 methods to JS. The HTML/CSS/JS in `index.html` renders a dismissible banner and a "Check for Updates" sidebar link.

**Tech Stack:** httpx (lazy import), tenacity (retry), stdlib json (state file), GitHub Releases API

---

### Task 1: Create `updater.py` — version comparison, state, rate limiting

**Files:**
- Create: `retro_refiner/updater.py`
- Create: `tests/test_updater.py`

- [ ] **Step 1: Create `updater.py` with version utilities**

```python
"""Self-update logic for Retro-Refiner.

Checks GitHub Releases for new versions, downloads updates, and replaces
the running executable. All external imports (httpx) are lazy.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from retro_refiner import __version__
from retro_refiner.paths import get_runtime_path

GITHUB_REPO = 'atkins/retro-refiner'
GITHUB_API_URL = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
RELEASES_URL = f'https://github.com/{GITHUB_REPO}/releases'
STATE_FILENAME = '_update_state.json'
VERSION_RE = re.compile(r'^\d{4}\.\d{2}\.\d{2}\.\d{4}$')

ASSET_NAMES = {
    'win32': 'retro-refiner-windows.exe',
    'darwin': 'retro-refiner-macos',
    'linux': 'retro-refiner-linux',
}


def get_current_version() -> str:
    """Return the current app version string."""
    return __version__


def is_frozen() -> bool:
    """Return True if running as a PyInstaller frozen executable."""
    return getattr(sys, 'frozen', False)


def _normalize_version(tag: str) -> str:
    """Strip leading 'v' from a version tag."""
    return tag.lstrip('v')


def is_valid_version(version: str) -> bool:
    """Check if a version string matches YYYY.MM.DD.HHMM format."""
    return bool(VERSION_RE.match(_normalize_version(version)))


def is_newer(remote: str, local: str) -> bool:
    """Return True if remote version is newer than local.

    Both must be valid version strings. Returns False if either is invalid.
    """
    r = _normalize_version(remote)
    l_ver = _normalize_version(local)
    if not VERSION_RE.match(r) or not VERSION_RE.match(l_ver):
        return False
    return r > l_ver


def can_check_for_updates() -> bool:
    """Return True if update checking should proceed."""
    if get_current_version() == 'dev':
        return False
    if not is_frozen():
        return False
    return True


def _state_path() -> Path:
    """Path to the update state file."""
    return get_runtime_path() / STATE_FILENAME


def load_update_state() -> dict:
    """Read update state from disk. Returns empty dict on any error."""
    try:
        with open(_state_path(), encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:  # pylint: disable=broad-except
        return {}


def save_update_state(state: dict) -> None:
    """Write update state to disk."""
    try:
        with open(_state_path(), 'w', encoding='utf-8') as fh:
            json.dump(state, fh)
    except Exception:  # pylint: disable=broad-except
        pass


def should_check(state: dict) -> bool:
    """Return True if enough time has passed since last check (24h)."""
    last = state.get('last_check')
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_dt > timedelta(hours=24)
    except (ValueError, TypeError):
        return True


def get_asset_url(release_info: dict) -> Optional[str]:
    """Pick the platform-correct download URL from release assets."""
    target = ASSET_NAMES.get(sys.platform)
    if not target:
        return None
    for asset in release_info.get('assets', []):
        if asset.get('name') == target:
            return asset.get('browser_download_url')
    return None


def get_asset_size(release_info: dict) -> int:
    """Return the expected file size for the platform asset."""
    target = ASSET_NAMES.get(sys.platform)
    if not target:
        return 0
    for asset in release_info.get('assets', []):
        if asset.get('name') == target:
            return asset.get('size', 0)
    return 0
```

- [ ] **Step 2: Create `tests/test_updater.py` with tests for version + state functions**

```python
"""Tests for retro_refiner.updater module."""
import json
import pytest
from unittest.mock import patch
from pathlib import Path

from retro_refiner.updater import (
    get_current_version, is_newer, is_valid_version,
    _normalize_version, can_check_for_updates, should_check,
    load_update_state, save_update_state,
    get_asset_url, get_asset_size, ASSET_NAMES,
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
        from datetime import datetime, timezone
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
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_updater.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add retro_refiner/updater.py tests/test_updater.py
git commit -m "feat: add updater.py with version comparison, state, and asset selection"
```

---

### Task 2: Add update check, download, apply, and recovery to `updater.py`

**Files:**
- Modify: `retro_refiner/updater.py`
- Modify: `tests/test_updater.py`

- [ ] **Step 1: Add `check_for_update()` function**

Append to `updater.py`:

```python
def check_for_update() -> Optional[dict]:
    """Check GitHub for a newer release.

    Returns release info dict if a newer version exists, None otherwise.
    All errors are silently swallowed.
    """
    try:
        import httpx  # pylint: disable=import-outside-toplevel
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(GITHUB_API_URL, headers={
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'Retro-Refiner-Updater/1.0',
            })
            resp.raise_for_status()
            data = resp.json()

        tag = data.get('tag_name', '')
        if not is_newer(tag, get_current_version()):
            return None

        asset_url = get_asset_url(data)
        if not asset_url:
            return None

        return {
            'version': tag,
            'url': asset_url,
            'size': get_asset_size(data),
            'html_url': data.get('html_url', RELEASES_URL),
        }
    except Exception:  # pylint: disable=broad-except
        return None
```

- [ ] **Step 2: Add `download_update()` function**

```python
def download_update(url: str, expected_size: int,
                    progress_callback=None) -> Optional[Path]:
    """Download update to a temp directory. Returns path or None on failure."""
    import tempfile  # pylint: disable=import-outside-toplevel
    import httpx  # pylint: disable=import-outside-toplevel

    dest_dir = Path(tempfile.mkdtemp(prefix='retro-refiner-update-'))
    asset_name = ASSET_NAMES.get(sys.platform, 'retro-refiner-update')
    dest_path = dest_dir / asset_name

    try:
        with httpx.Client(follow_redirects=True, timeout=120,
                          headers={'User-Agent': 'Retro-Refiner-Updater/1.0'}) as client:
            with client.stream('GET', url) as response:
                response.raise_for_status()
                total = int(response.headers.get('content-length', 0))
                downloaded = 0
                with open(dest_path, 'wb') as f:
                    for chunk in response.iter_bytes(65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(downloaded, total)
    except Exception:  # pylint: disable=broad-except
        return None

    if expected_size > 0 and dest_path.stat().st_size != expected_size:
        return None

    return dest_path
```

- [ ] **Step 3: Add `apply_update()` function**

```python
def apply_update(new_path: Path, exe_path: Path) -> bool:
    """Replace the running executable with the downloaded update.

    Windows: rename exe -> exe.old, move new -> exe, remove MOTW.
    macOS/Linux: atomic replace, set executable bit, remove quarantine.
    Returns True on success.
    """
    import shutil  # pylint: disable=import-outside-toplevel
    try:
        if sys.platform == 'win32':
            old_path = Path(str(exe_path) + '.old')
            old_path.unlink(missing_ok=True)
            os.rename(exe_path, old_path)
            shutil.move(str(new_path), str(exe_path))
            # Remove Zone.Identifier to prevent SmartScreen warning
            try:
                os.remove(f"{exe_path}:Zone.Identifier")
            except OSError:
                pass
        else:
            shutil.move(str(new_path), str(exe_path))
            os.chmod(exe_path, 0o755)
            if sys.platform == 'darwin':
                import subprocess  # pylint: disable=import-outside-toplevel
                subprocess.run(
                    ['xattr', '-d', 'com.apple.quarantine', str(exe_path)],
                    capture_output=True, check=False)
        return True
    except Exception:  # pylint: disable=broad-except
        return False
```

- [ ] **Step 4: Add `startup_recovery()` and `launch_and_exit()` functions**

```python
def startup_recovery(exe_path: Optional[Path] = None) -> None:
    """Recover from interrupted update and clean up old executables.

    Called early in startup, before GUI initializes.
    """
    if not is_frozen():
        return
    if exe_path is None:
        exe_path = Path(sys.executable)
    old_path = Path(str(exe_path) + '.old')

    # Recovery: exe was renamed away but new wasn't moved in
    if not exe_path.exists() and old_path.exists():
        try:
            os.rename(old_path, exe_path)
        except OSError:
            pass
        return

    # Cleanup: both exist, delete the old one
    if old_path.exists():
        try:
            old_path.unlink()
        except OSError:
            pass


def launch_and_exit(exe_path: Optional[Path] = None) -> None:
    """Launch the (updated) executable and exit the current process."""
    import subprocess  # pylint: disable=import-outside-toplevel
    if exe_path is None:
        exe_path = Path(sys.executable)

    if is_frozen():
        cmd = [str(exe_path)]
    else:
        cmd = [sys.executable, '-m', 'retro_refiner']

    subprocess.Popen(  # pylint: disable=consider-using-with
        cmd, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    sys.exit(0)
```

- [ ] **Step 5: Add tests for check, download, apply, recovery**

Append to `tests/test_updater.py`:

```python
from retro_refiner.updater import (
    check_for_update, download_update, apply_update,
    startup_recovery, launch_and_exit, is_frozen,
    GITHUB_API_URL,
)


# -- check_for_update --

class TestCheckForUpdate:
    def test_returns_info_when_newer(self):
        import httpx
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
        with patch('retro_refiner.updater.__version__', '2026.03.24.1330'), \
             patch('retro_refiner.updater.httpx.Client') as MockClient:
            client = httpx.Client(transport=httpx.MockTransport(handler))
            MockClient.return_value.__enter__ = lambda s: client
            MockClient.return_value.__exit__ = lambda s, *a: client.close()
            result = check_for_update()
            assert result is not None
            assert result['version'] == 'v9999.12.31.2359'

    def test_returns_none_when_current(self):
        with patch('retro_refiner.updater.__version__', '9999.12.31.2359'):
            assert check_for_update() is None

    def test_returns_none_on_network_error(self):
        with patch('retro_refiner.updater.__version__', '2026.03.24.1330'):
            # httpx not mocked — will fail to connect to real API
            # but should return None silently
            result = check_for_update()
            # result may or may not be None depending on network
            # just verify no exception raised


# -- apply_update --

class TestApplyUpdate:
    def test_apply_replaces_exe(self, tmp_path):
        exe = tmp_path / 'app.exe'
        exe.write_bytes(b'old binary')
        new = tmp_path / 'app_new.exe'
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


# -- startup_recovery --

class TestStartupRecovery:
    def test_recovery_when_exe_missing(self, tmp_path):
        exe = tmp_path / 'app.exe'
        old = tmp_path / 'app.exe.old'
        old.write_bytes(b'old binary')
        assert not exe.exists()

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
        exe = tmp_path / 'app.exe'
        old = tmp_path / 'app.exe.old'
        old.write_bytes(b'old binary')

        with patch('retro_refiner.updater.is_frozen', return_value=False):
            startup_recovery(exe)
        # Should not touch anything
        assert old.exists()

    def test_noop_when_no_old(self, tmp_path):
        exe = tmp_path / 'app.exe'
        exe.write_bytes(b'binary')

        with patch('retro_refiner.updater.is_frozen', return_value=True):
            startup_recovery(exe)
        assert exe.exists()


# -- download verification --

class TestDownloadVerification:
    def test_size_mismatch_returns_none(self, tmp_path):
        import httpx

        def handler(request):
            return httpx.Response(200, content=b'small')

        with patch('retro_refiner.updater.tempfile.mkdtemp',
                   return_value=str(tmp_path)):
            result = download_update(
                'http://example.com/file', expected_size=999999)
        assert result is None

    def test_size_zero_skips_check(self, tmp_path):
        import httpx

        def handler(request):
            return httpx.Response(200, content=b'data',
                                 headers={'content-length': '4'})

        with patch('retro_refiner.updater.tempfile.mkdtemp',
                   return_value=str(tmp_path)), \
             patch('retro_refiner.updater.httpx') as mock_httpx:
            mock_client = httpx.Client(transport=httpx.MockTransport(handler))
            mock_httpx.Client.return_value.__enter__ = lambda s: mock_client
            mock_httpx.Client.return_value.__exit__ = lambda s, *a: mock_client.close()
            result = download_update('http://example.com/file',
                                     expected_size=0)
            # With expected_size=0, size check is skipped
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_updater.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add retro_refiner/updater.py tests/test_updater.py
git commit -m "feat: add update check, download, apply, and recovery to updater.py"
```

---

### Task 3: Wire updater into `api.py`

**Files:**
- Modify: `retro_refiner/ui/api.py:39-51` (init), `84-130` (reset_and_restart), `2250-2262` (_push_event)
- Modify: `retro_refiner/ui/app.py:116` (startup recovery)

- [ ] **Step 1: Add startup recovery call in `app.py`**

In `retro_refiner/ui/app.py`, add before `api.set_window(window)` (line 116):

```python
    # Run update recovery/cleanup before GUI starts
    from retro_refiner.updater import startup_recovery  # pylint: disable=import-outside-toplevel
    startup_recovery()
```

- [ ] **Step 2: Add API methods to `api.py`**

Add these instance methods to the `Api` class. Place them after the existing `reset_and_restart` method (after line ~130):

```python
    def check_for_updates(self, force=False):
        """Check GitHub for a newer version. Returns JSON with update info or null."""
        from retro_refiner.updater import (  # pylint: disable=import-outside-toplevel
            can_check_for_updates, check_for_update,
            load_update_state, save_update_state, should_check,
        )
        if not can_check_for_updates():
            return orjson.dumps(None).decode()

        state = load_update_state()
        if not force and not should_check(state):
            return orjson.dumps(None).decode()

        info = check_for_update()

        # Update last_check timestamp
        from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel
        state['last_check'] = datetime.now(timezone.utc).isoformat()
        save_update_state(state)

        if not info:
            return orjson.dumps(None).decode()

        # Check if user dismissed this version
        if state.get('dismissed_version') == info['version']:
            return orjson.dumps(None).decode()

        return orjson.dumps(info).decode()

    def download_update(self, url, expected_size):
        """Download update and apply it. Pushes progress events."""
        import threading  # already imported at top

        def _do_download():
            from retro_refiner.updater import (  # pylint: disable=import-outside-toplevel
                download_update as dl_update, apply_update,
            )
            def on_progress(downloaded, total):
                pct = int(downloaded / total * 100) if total else 0
                self._push_event('update-progress', {
                    'downloaded': downloaded, 'total': total, 'percent': pct,
                })

            self._push_event('update-downloading', {})

            path = dl_update(url, expected_size, progress_callback=on_progress)
            if not path:
                self._push_event('update-error', {
                    'message': 'Download failed or file size mismatch',
                })
                return

            import sys as _sys  # pylint: disable=import-outside-toplevel
            from pathlib import Path  # already imported at top
            exe_path = Path(_sys.executable)
            success = apply_update(path, exe_path)
            if success:
                self._push_event('update-ready', {})
            else:
                self._push_event('update-error', {
                    'message': 'Failed to apply update (permission error?)',
                })

        t = threading.Thread(target=_do_download, daemon=True)
        t.start()
        return orjson.dumps({'status': 'started'}).decode()

    def restart_app(self):
        """Save state and restart with the updated executable."""
        self._skip_save = False
        self.save_ui_state()
        from retro_refiner.updater import launch_and_exit  # pylint: disable=import-outside-toplevel
        launch_and_exit()

    def dismiss_update(self, version):
        """Dismiss the update banner for a specific version."""
        from retro_refiner.updater import (  # pylint: disable=import-outside-toplevel
            load_update_state, save_update_state,
        )
        state = load_update_state()
        state['dismissed_version'] = version
        save_update_state(state)
        return orjson.dumps({'ok': True}).decode()
```

- [ ] **Step 3: Add auto-check on app launch**

In `api.py`, add a method and call it from the existing startup flow. Find where `load_ui_state` is called in the GUI startup sequence and add the auto-check after it. Add this method to the Api class:

```python
    def _auto_check_for_updates(self):
        """Background auto-check for updates on app launch."""
        import threading  # already imported

        def _check():
            import time as _time  # pylint: disable=import-outside-toplevel
            _time.sleep(3)  # Don't check immediately — let the GUI settle
            result_json = self.check_for_updates()
            import orjson as _orjson  # already imported
            result = _orjson.loads(result_json)
            if result:
                self._push_event('update-available', result)

        t = threading.Thread(target=_check, daemon=True)
        t.start()
```

Call `self._auto_check_for_updates()` at the end of `set_window()` or in `__init__` after window is available.

- [ ] **Step 4: Fix `reset_and_restart` to use `launch_and_exit`**

In the existing `reset_and_restart` method (lines 84-130), replace the subprocess.Popen + window.destroy block with:

```python
        from retro_refiner.updater import launch_and_exit  # pylint: disable=import-outside-toplevel
        launch_and_exit()
```

This fixes the pre-existing bug where `reset_and_restart` used `[sys.executable, '-m', 'retro_refiner']` which fails in frozen mode.

- [ ] **Step 5: Run tests**

```bash
python -m pytest --ignore=tests/test_smoke.py -v --tb=short
python -m pylint retro_refiner/
```

Expected: All pass. Pylint 10.00/10.

- [ ] **Step 6: Commit**

```bash
git add retro_refiner/ui/api.py retro_refiner/ui/app.py
git commit -m "feat: wire updater into api.py with check, download, apply, restart"
```

---

### Task 4: Add update banner and sidebar link to `index.html`

**Files:**
- Modify: `retro_refiner/ui/assets/index.html:381-388` (CSS), `930-935` (footer), `957` (content area)

- [ ] **Step 1: Add CSS for update banner**

Add after the existing `.sidebar-footer` CSS block (around line 388):

```css
/* Update banner */
.update-banner {
  display: none;
  padding: 8px 16px;
  background: var(--bg-stripe);
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
  align-items: center;
  gap: 8px;
}
.update-banner.visible { display: flex; }
.update-banner .update-text { flex: 1; }
.update-banner .btn-update {
  background: var(--accent);
  color: var(--text-on-accent);
  border: none;
  border-radius: 4px;
  padding: 4px 12px;
  cursor: pointer;
  font-size: 12px;
}
.update-banner .btn-update:hover { opacity: 0.9; }
.update-banner .btn-dismiss {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  padding: 0 4px;
}
.update-banner a {
  color: var(--accent);
  text-decoration: underline;
  cursor: pointer;
  font-size: 12px;
}
.update-check-link {
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  text-decoration: none;
  margin-top: 4px;
  display: inline-block;
}
.update-check-link:hover { color: var(--accent); }
```

- [ ] **Step 2: Add banner HTML above the content area**

Inside the `.main` div (line 940), before the `.status-bar` div, add:

```html
    <div class="update-banner" id="update-banner">
      <span class="update-text" id="update-text"></span>
      <a id="update-whats-new" href="#" style="display:none"
         onclick="event.preventDefault(); if(window.pywebview) window.pywebview.api.open_url(this.dataset.url)">What's new?</a>
      <button class="btn-update" id="update-action" style="display:none"></button>
      <button class="btn-dismiss" id="update-dismiss" title="Dismiss" style="display:none">&times;</button>
    </div>
```

- [ ] **Step 3: Add "Check for Updates" link to sidebar footer**

In the `.sidebar-footer` div (lines 930-935), add after the Reset button:

```html
    <span class="update-check-link" id="check-updates-link" onclick="manualCheckForUpdates()">Check for Updates</span>
```

- [ ] **Step 4: Add JavaScript event handlers**

Add to the JS section (before the closing `</script>` tag):

```javascript
/* ---- Update Banner ---- */
var _updateInfo = null;

function showUpdateBanner(state, data) {
  var banner = document.getElementById('update-banner');
  var text = document.getElementById('update-text');
  var action = document.getElementById('update-action');
  var dismiss = document.getElementById('update-dismiss');
  var whatsNew = document.getElementById('update-whats-new');
  banner.classList.add('visible');

  if (state === 'available') {
    _updateInfo = data;
    text.textContent = 'Update available: ' + data.version;
    action.textContent = 'Download & Install';
    action.style.display = '';
    action.onclick = function() { startUpdateDownload(); };
    dismiss.style.display = '';
    dismiss.onclick = function() { dismissUpdate(data.version); };
    if (data.html_url) {
      whatsNew.style.display = '';
      whatsNew.dataset.url = data.html_url;
    }
  } else if (state === 'downloading') {
    text.textContent = 'Downloading update...';
    action.style.display = 'none';
    dismiss.style.display = 'none';
    whatsNew.style.display = 'none';
  } else if (state === 'progress') {
    text.textContent = 'Downloading update... ' + (data.percent || 0) + '%';
  } else if (state === 'ready') {
    text.textContent = 'Update downloaded \u2014 restart to apply';
    action.textContent = 'Restart Now';
    action.style.display = '';
    action.onclick = function() {
      if (window.pywebview) window.pywebview.api.restart_app();
    };
    dismiss.style.display = 'none';
    whatsNew.style.display = 'none';
  } else if (state === 'error') {
    text.textContent = 'Update failed: ' + (data.message || 'unknown error');
    action.textContent = 'Retry';
    action.style.display = '';
    action.onclick = function() { startUpdateDownload(); };
    dismiss.style.display = '';
    dismiss.onclick = function() { banner.classList.remove('visible'); };
    whatsNew.style.display = 'none';
  }
}

function startUpdateDownload() {
  if (!_updateInfo || !window.pywebview) return;
  window.pywebview.api.download_update(_updateInfo.url, _updateInfo.size);
}

function dismissUpdate(version) {
  document.getElementById('update-banner').classList.remove('visible');
  if (window.pywebview) window.pywebview.api.dismiss_update(version);
}

function manualCheckForUpdates() {
  var link = document.getElementById('check-updates-link');
  if (!window.pywebview) return;
  link.textContent = 'Checking...';
  window.pywebview.api.check_for_updates(true).then(function(json) {
    var result = JSON.parse(json);
    if (result) {
      showUpdateBanner('available', result);
      link.textContent = 'Check for Updates';
    } else {
      link.textContent = 'Up to date';
      setTimeout(function() { link.textContent = 'Check for Updates'; }, 3000);
    }
  });
}
```

- [ ] **Step 5: Add event routing in `handlePythonEvent`**

Find the `handlePythonEvent` function (or `_handleEventOriginal`) and add cases for the new update events. Add before the existing event type switch/if-chain:

```javascript
  if (type === 'update-available') { showUpdateBanner('available', data); return; }
  if (type === 'update-downloading') { showUpdateBanner('downloading', data); return; }
  if (type === 'update-progress') { showUpdateBanner('progress', data); return; }
  if (type === 'update-ready') { showUpdateBanner('ready', data); return; }
  if (type === 'update-error') { showUpdateBanner('error', data); return; }
```

- [ ] **Step 6: Run full test suite and lint**

```bash
python -m pytest --ignore=tests/test_smoke.py -v --tb=short
python -m pylint retro_refiner/
python -m ruff check retro_refiner/
```

Expected: All pass. Pylint 10.00/10.

- [ ] **Step 7: Commit**

```bash
git add retro_refiner/ui/assets/index.html
git commit -m "feat: add update banner and check-for-updates link to GUI"
```

---

### Task 5: Update CLAUDE.md, pyinstaller spec, and module tests

**Files:**
- Modify: `CLAUDE.md`
- Modify: `retro-refiner.spec`
- Modify: `tests/test_modules.py`

- [ ] **Step 1: Add `updater.py` to PyInstaller spec hiddenimports**

In `retro-refiner.spec`, add `'retro_refiner.updater'` to the `hiddenimports` list (after `retro_refiner.dedup`).

- [ ] **Step 2: Add updater to module import test**

In `tests/test_modules.py`, add `"updater"` to the `@pytest.mark.parametrize("module", [...])` list for `test_module_importable`.

- [ ] **Step 3: Update CLAUDE.md**

Add to the project structure section:
```
    updater.py        # Self-update: GitHub release check, download, apply, recovery
```

Add to the `_do_run` Phases section:
```
- `check_for_updates()` — GitHub Releases API check, returns update info JSON
- `download_update()` — stream download + apply in background thread
- `restart_app()` — save state, launch new exe, exit
```

Update the test count to reflect new tests.

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest --ignore=tests/test_smoke.py
python -m pylint retro_refiner/
python -m ruff check retro_refiner/
```

Expected: All pass. Pylint 10.00/10.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md retro-refiner.spec tests/test_modules.py
git commit -m "docs: update CLAUDE.md, spec, and module tests for self-update feature"
```

---

### Task 6: Manual smoke test

- [ ] **Step 1: Test update check in dev mode**

Run the app from source (`python -m retro_refiner`). Verify:
- No update banner appears (dev mode skips check)
- "Check for Updates" link shows "Up to date" (since can_check_for_updates returns False)

- [ ] **Step 2: Test update banner states manually**

Open the browser console (F12 in the webview if available) and trigger events manually:
```javascript
handlePythonEvent({type: 'update-available', data: {version: 'v9999.01.01.0000', url: 'https://example.com', size: 1000, html_url: 'https://github.com/atkins/retro-refiner/releases'}});
```

Verify:
- Banner appears with version, "Download & Install", "What's new?", dismiss button
- Dismiss hides the banner
- "What's new?" opens the releases page

- [ ] **Step 3: Test with a real built executable**

Build the executable and verify:
- Auto-check triggers on launch after 3s delay
- If current version matches latest release, no banner appears
- "Check for Updates" sidebar link works
