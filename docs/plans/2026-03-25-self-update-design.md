# Self-Update Feature Design

## Goal

Add automatic update checking and self-update capability so users running the built executable can update to the latest release without manually downloading from GitHub.

## Overview

On launch, the app checks the GitHub Releases API for a newer version. If found, a dismissible banner appears offering to download and install the update. Users can also manually trigger a check from the sidebar footer. After downloading, the running executable is replaced in-place via a rename trick (Windows) or atomic replace (macOS/Linux). The user is prompted to restart to apply.

## Update Check

- On app launch, spawn a daemon thread that fetches `https://api.github.com/repos/atkins/retro-refiner/releases/latest` via httpx (lazy import)
- Parse the tag name (e.g. `v2026.03.24.1330`) and compare against `__version__`
- Validate version format with regex `\d{4}\.\d{2}\.\d{2}\.\d{4}` before comparing — skip if either side doesn't match
- If `__version__ == "dev"` or `not getattr(sys, 'frozen', False)`, skip the check entirely
- Rate-limit: skip if the last successful check was within the past 24 hours
- Last check timestamp stored in `_update_state.json` (separate file, see State section)
- Silent on any failure — network errors, API rate limits, parse errors all fail silently
- The check runs in a background thread and pushes results via `_push_event()`

## UI

### Banner (top of main panel)

When an update is found, push an `update-available` event to JS. A dismissible banner renders at the top of the main panel area (above the log/results/picker tabs):

- **Available state**: `"Update available: vX.X.X.X"` with a "Download & Install" button, a "What's new?" link (opens release page in browser), and an "x" dismiss button
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
- Verify `getattr(sys, 'frozen', False)` — only proceed if running as frozen executable
- Platform asset name mapping:
  - Windows: `retro-refiner-windows.exe`
  - macOS: `retro-refiner-macos`
  - Linux: `retro-refiner-linux`
- Download target: temp directory via `tempfile.mkdtemp()` (avoids permission issues if exe is in Program Files or /usr/local/bin)

### Step 2: Download

- Fetch the asset download URL from the GitHub release JSON (`assets[].browser_download_url`)
- Stream download via httpx to temp directory (lazy import, uses tenacity retry)
- After download, verify file size matches `assets[].size` from the API response — abort if mismatch (catches truncation/corruption)
- Push progress events to update the banner

### Step 3: Replace

**Windows:**
1. Rename running executable: `{exe_path}` -> `{exe_path}.old`
2. Move downloaded file from temp dir to `{exe_path}`
3. Remove Zone.Identifier ADS to prevent SmartScreen warning:
   ```python
   try:
       os.remove(f"{exe_path}:Zone.Identifier")
   except OSError:
       pass
   ```
4. Windows allows renaming a locked/running file but not deleting it

**macOS/Linux:**
1. Move downloaded file from temp dir to `{exe_path}` via `os.replace()` (atomic)
2. `os.chmod({exe_path}, 0o755)` (preserve executable bit)
3. macOS: remove quarantine attribute:
   ```python
   subprocess.run(['xattr', '-d', 'com.apple.quarantine', str(exe_path)],
                  capture_output=True, check=False)
   ```

### Step 4: Prompt restart

Push `update-ready` event to JS. Banner changes to "Restart to apply" with "Restart Now" button.

### Step 5: Restart (user-initiated)

1. Save current config state
2. Detect execution mode:
   - Frozen (`getattr(sys, 'frozen', False)`): launch `[exe_path]`
   - Dev mode: launch `[sys.executable, '-m', 'retro_refiner']`
3. Launch via `subprocess.Popen(cmd, start_new_session=True)`
4. Exit current process: `sys.exit(0)`

### Step 6: Startup recovery and cleanup

On startup, before any other logic:
1. **Recovery**: If `{exe_path}` is missing but `{exe_path}.old` exists, rename `.old` back to the original name (crash recovery — update was interrupted between renames)
2. **Cleanup**: If `{exe_path}.old` exists alongside a working `{exe_path}`, delete `.old`

## State

Update state is stored in a separate file `_update_state.json` in the runtime directory (alongside the existing state file). This avoids modifying the Config dataclass or the state file save/load logic.

```json
{
  "last_check": "2026-03-25T10:00:00",
  "dismissed_version": null
}
```

Managed entirely by `updater.py` — read/write with stdlib `json` (not orjson, since this is simple file I/O).

## Version Comparison

Version strings are date-based: `v2026.03.24.1330`. After stripping the `v` prefix, lexicographic string comparison works correctly (YYYY.MM.DD.HHMM sorts chronologically). Both local and remote versions must match the regex `\d{4}\.\d{2}\.\d{2}\.\d{4}` — skip comparison if either is malformed.

## Error Handling

| Error | Action |
|-------|--------|
| Network failure during check | Silent — no UI change |
| GitHub API rate limit (403) | Silent — retry on next launch |
| Download failure (network) | Banner shows error with "Retry" button |
| Download failure (disk full) | Banner shows error with manual download link |
| Downloaded file size mismatch | Banner shows error with "Retry" button |
| File rename failure (permissions) | Banner shows error, suggest manual download |
| Crash during rename (Windows) | Startup recovery restores `.old` to original name |
| `__version__ == "dev"` | Skip all update logic |
| Not frozen / no `sys.executable` | Skip all update logic |
| Malformed version string | Skip comparison, no UI change |

## Architecture

### Files

| File | Changes |
|------|---------|
| `retro_refiner/updater.py` | NEW — update check, download, replace, restart logic |
| `retro_refiner/ui/api.py` | Add `check_for_updates()`, `download_update()`, `restart_app()` API methods; call updater on startup |
| `retro_refiner/ui/assets/index.html` | Add update banner HTML/CSS/JS, sidebar "Check for Updates" link |
| `retro_refiner/__init__.py` | No change (already has `__version__`) |

### `updater.py` module

Standalone module with no GUI dependencies. All external imports (httpx) are lazy. Functions:

- `is_update_available() -> Optional[dict]` — checks GitHub API, returns release info dict or None
- `get_current_version() -> str` — returns `__version__`
- `is_newer(remote_version, local_version) -> bool` — version comparison with format validation
- `get_asset_url(release_info) -> Optional[str]` — picks platform-correct asset URL
- `get_asset_size(release_info) -> int` — returns expected file size for verification
- `download_update(url, dest_dir, progress_callback=None) -> Path` — streams download to temp dir
- `verify_download(path, expected_size) -> bool` — file size check
- `apply_update(new_path, exe_path) -> bool` — rename trick + platform-specific cleanup (MOTW, quarantine)
- `startup_recovery(exe_path)` — restore `.old` if exe is missing, delete `.old` if both exist
- `should_check(last_check_time) -> bool` — 24-hour rate limit
- `load_update_state() -> dict` — read `_update_state.json`
- `save_update_state(state)` — write `_update_state.json`
- `launch_and_exit(exe_path)` — subprocess + sys.exit, handles frozen vs dev mode

### API methods (exposed to JS)

- `check_for_updates()` — returns JSON with version info or null
- `download_update()` — triggers download, pushes progress events
- `restart_app()` — saves state, launches new exe, exits
- `dismiss_update(version)` — stores dismissed version in state

## Dependencies

No new dependencies. Uses existing httpx (lazy import for GitHub API + download) and tenacity (retry). Both are already included in PyInstaller builds. The `updater.py` module uses lazy imports so it works gracefully when httpx is not installed (dev/source mode skips update logic anyway).

## Testing

- Unit tests for `updater.py`: version comparison, format validation, asset URL selection, rate limiting, state persistence
- Mock httpx for API check tests (MockTransport)
- Mock `os.rename`/`os.replace` for update application tests
- Test startup recovery logic (missing exe + .old exists)
- Test file size verification
- Skip in smoke tests (don't hit GitHub API in CI)
