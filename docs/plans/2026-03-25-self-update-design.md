# Self-Update Feature Design

## Goal

Add automatic update checking and self-update capability so users running the built executable can update to the latest release without manually downloading from GitHub.

## Overview

On launch, the app checks the GitHub Releases API for a newer version. If found, a dismissible banner appears offering to download and install the update. Users can also manually trigger a check from the sidebar footer. After downloading, the running executable is replaced in-place via a rename trick (Windows) or atomic replace (macOS/Linux). The user is prompted to restart to apply.

## Update Check

- On app launch, spawn a daemon thread that fetches `https://api.github.com/repos/atkins/retro-refiner/releases/latest` via httpx
- Parse the tag name (e.g. `v2026.03.24.1330`) and compare against `__version__`
- If `__version__ == "dev"`, skip the check entirely (running from source)
- Rate-limit: skip if the last successful check was within the past 24 hours
- Last check timestamp stored in the state file (`.retro-refiner-state.yaml`)
- Silent on any failure — network errors, API rate limits, parse errors all fail silently
- The check runs in a background thread and pushes results via `_push_event()`

## UI

### Banner (top of main panel)

When an update is found, push an `update-available` event to JS. A dismissible banner renders at the top of the main panel area (above the log/results/picker tabs):

- **Available state**: `"Update available: vX.X.X.X"` with a "Download & Install" button and an "x" dismiss button
- **Downloading state**: `"Downloading update..."` with a progress indicator
- **Ready state**: `"Update downloaded — restart to apply"` with a "Restart Now" button
- **Error state**: `"Update failed: {reason}"` with a "Retry" button and a "Download manually" link to the GitHub releases page

Dismissing the banner for a specific version stores `dismissed_version` in state — the banner won't reappear for that version on subsequent launches.

### Sidebar footer

A "Check for Updates" text link below the existing Save/Load/Reset buttons. Clicking triggers a manual check (bypasses the 24-hour rate limit). Shows brief inline feedback:
- "Checking..." while in progress
- "Up to date" if no update found (auto-clears after 3 seconds)
- Triggers the banner if an update is found

## Self-Update Mechanism

### Step 1: Determine paths

- Current executable: `sys.executable` (PyInstaller sets this to the built .exe path)
- Platform asset name mapping:
  - Windows: `retro-refiner-windows.exe`
  - macOS: `retro-refiner-macos`
  - Linux: `retro-refiner-linux`
- Download target: `{exe_path}.new` (same directory as running executable)

### Step 2: Download

- Fetch the asset download URL from the GitHub release JSON (`assets[].browser_download_url`)
- Stream download via httpx to `{exe_path}.new` (uses existing `stream_download` with tenacity retry)
- Push progress events to update the banner

### Step 3: Replace

**Windows:**
1. Rename running executable: `{exe_path}` -> `{exe_path}.old`
2. Rename downloaded: `{exe_path}.new` -> `{exe_path}`
3. Windows allows renaming a locked/running file but not deleting it

**macOS/Linux:**
1. `os.replace({exe_path}.new, {exe_path})` (atomic replace)
2. `os.chmod({exe_path}, 0o755)` (preserve executable bit)

### Step 4: Prompt restart

Push `update-ready` event to JS. Banner changes to "Restart to apply" with "Restart Now" button.

### Step 5: Restart (user-initiated)

1. Save current config state
2. Launch new executable: `subprocess.Popen([exe_path], ...)`
3. Exit current process: `sys.exit(0)`

### Step 6: Cleanup (next launch)

On startup, check for and delete `{exe_path}.old` if it exists.

## State

Add `update` section to the existing state file schema:

```yaml
update:
  last_check: "2026-03-25T10:00:00"
  dismissed_version: null
```

These fields are added to the state dict that's already persisted to `.retro-refiner-state.yaml`. Not part of the Config dataclass — stored as top-level keys in the state file alongside the existing config data.

## Version Comparison

Version strings are date-based: `v2026.03.24.1330`. After stripping the `v` prefix, lexicographic string comparison works correctly for determining which is newer (YYYY.MM.DD.HHMM format sorts chronologically).

## Error Handling

| Error | Action |
|-------|--------|
| Network failure during check | Silent — no UI change |
| GitHub API rate limit (403) | Silent — retry on next launch |
| Download failure (network) | Banner shows error with "Retry" button |
| Download failure (disk full) | Banner shows error with manual download link |
| File rename failure (permissions) | Banner shows error, suggest manual download |
| `__version__ == "dev"` | Skip all update logic |
| No `sys.executable` / not frozen | Skip all update logic |

## Architecture

### Files

| File | Changes |
|------|---------|
| `retro_refiner/updater.py` | NEW — update check, download, replace, restart logic |
| `retro_refiner/ui/api.py` | Add `check_for_updates()`, `download_update()`, `restart_app()` API methods; call updater on startup |
| `retro_refiner/ui/assets/index.html` | Add update banner HTML/CSS/JS, sidebar "Check for Updates" link |
| `retro_refiner/__init__.py` | No change (already has `__version__`) |

### `updater.py` module

Standalone module with no GUI dependencies. Functions:

- `is_update_available() -> Optional[dict]` — checks GitHub API, returns release info dict or None
- `get_current_version() -> str` — returns `__version__`
- `is_newer(remote_version, local_version) -> bool` — version comparison
- `get_asset_url(release_info) -> Optional[str]` — picks platform-correct asset URL
- `download_update(url, dest_path, progress_callback=None) -> bool` — streams download
- `apply_update(new_path, exe_path) -> bool` — rename trick
- `cleanup_old_executable(exe_path)` — delete .old file
- `should_check(last_check_time) -> bool` — 24-hour rate limit
- `launch_and_exit(exe_path)` — subprocess + sys.exit

### API methods (exposed to JS)

- `check_for_updates()` — returns JSON with version info or null
- `download_update()` — triggers download, pushes progress events
- `restart_app()` — saves state, launches new exe, exits
- `dismiss_update(version)` — stores dismissed version in state

## Dependencies

No new dependencies. Uses existing httpx (for GitHub API + download) and tenacity (for retry).

## Testing

- Unit tests for `updater.py`: version comparison, asset URL selection, rate limiting
- Mock `httpx.Client` for API check tests
- Mock `os.rename`/`os.replace` for update application tests
- Skip in smoke tests (don't hit GitHub API in CI)
