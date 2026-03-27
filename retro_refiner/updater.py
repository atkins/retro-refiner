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
from retro_refiner.log import logger
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
    """Return True if running as a bundled executable (PyInstaller or Nuitka)."""
    from retro_refiner.paths import is_bundled  # pylint: disable=import-outside-toplevel
    return is_bundled()


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


def check_for_update() -> Optional[dict]:
    """Check GitHub for a newer release.

    Returns dict with keys (version, url, size, html_url) if newer exists.
    Returns None if up-to-date or on any error (silent failure).
    """
    logger.debug("Checking for updates (current: {})", get_current_version())
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
            logger.debug("Up to date (latest: {})", tag)
            return None

        asset_url = get_asset_url(data)
        if not asset_url:
            logger.warning("Update {} found but no asset for platform '{}'",
                           tag, sys.platform)
            return None

        logger.info("Update available: {} -> {}", get_current_version(), tag)
        return {
            'version': tag,
            'url': asset_url,
            'size': get_asset_size(data),
            'html_url': data.get('html_url', RELEASES_URL),
        }
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Update check failed: {}", exc)
        return None


def download_update(url: str, expected_size: int,
                    progress_callback=None) -> Optional[Path]:
    """Download update to a temp directory. Returns path or None on failure."""
    import tempfile  # pylint: disable=import-outside-toplevel
    import httpx  # pylint: disable=import-outside-toplevel

    dest_dir = Path(tempfile.mkdtemp(prefix='retro-refiner-update-'))
    asset_name = ASSET_NAMES.get(sys.platform, 'retro-refiner-update')
    dest_path = dest_dir / asset_name

    logger.info("Downloading update from {}", url)
    try:
        with httpx.Client(follow_redirects=True, timeout=120,
                          headers={'User-Agent': 'Retro-Refiner-Updater/1.0'}
                          ) as client:
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
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Update download failed: {}", exc)
        return None

    actual_size = dest_path.stat().st_size
    if expected_size > 0 and actual_size != expected_size:
        logger.error("Update size mismatch: expected {} got {}",
                     expected_size, actual_size)
        return None

    logger.info("Update downloaded to {} ({} bytes)", dest_path, actual_size)
    return dest_path


def apply_update(new_path: Path, exe_path: Path) -> bool:
    """Replace the running executable with the downloaded update.

    Windows: rename exe -> exe.old, move new -> exe, remove MOTW.
    macOS/Linux: move new -> exe, set executable bit, remove quarantine.
    Returns True on success.
    """
    import shutil  # pylint: disable=import-outside-toplevel
    logger.info("Applying update: {} -> {}", new_path, exe_path)
    try:
        if sys.platform == 'win32':
            old_path = Path(str(exe_path) + '.old')
            old_path.unlink(missing_ok=True)
            os.rename(exe_path, old_path)
            logger.debug("Renamed {} -> {}", exe_path, old_path)
            shutil.move(str(new_path), str(exe_path))
            logger.debug("Moved {} -> {}", new_path, exe_path)
            try:
                os.remove(f"{exe_path}:Zone.Identifier")
            except OSError:
                pass
        else:
            shutil.move(str(new_path), str(exe_path))
            os.chmod(exe_path, 0o755)
            logger.debug("Replaced {} and set executable", exe_path)
            if sys.platform == 'darwin':
                import subprocess  # pylint: disable=import-outside-toplevel
                subprocess.run(
                    ['xattr', '-d', 'com.apple.quarantine', str(exe_path)],
                    capture_output=True, check=False)
        logger.info("Update applied successfully")
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to apply update: {}", exc)
        return False


def startup_recovery(exe_path: Optional[Path] = None) -> None:
    """Recover from interrupted update and clean up old executables."""
    if not is_frozen():
        return
    if exe_path is None:
        exe_path = Path(sys.executable)
    old_path = Path(str(exe_path) + '.old')

    if not exe_path.exists() and old_path.exists():
        logger.warning("Update recovery: restoring {} from {}", exe_path, old_path)
        try:
            os.rename(old_path, exe_path)
        except OSError as exc:
            logger.error("Recovery failed: {}", exc)
        return

    if old_path.exists():
        logger.debug("Cleaning up old executable: {}", old_path)
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

    logger.info("Relaunching: {}", ' '.join(cmd))
    subprocess.Popen(  # pylint: disable=consider-using-with
        cmd, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    sys.exit(0)
