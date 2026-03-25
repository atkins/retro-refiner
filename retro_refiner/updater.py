"""Self-update logic for Retro-Refiner.

Checks GitHub Releases for new versions, downloads updates, and replaces
the running executable. All external imports (httpx) are lazy.
"""
import json
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
