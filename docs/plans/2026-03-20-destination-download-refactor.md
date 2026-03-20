# Destination & Download Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the cache→copy pattern for remote downloads, download directly to destination, add destination validation and cleaning, and split "File action" into local-only actions vs implicit remote download.

**Architecture:** Remote files download directly to the destination folder (via temp file + rename for crash safety). Local files keep the existing transfer modes (copy/move/remove/hardlink/symlink). Two new destination options — "Validate existing" (size-based by default, CRC opt-in) and "Clean destination" — control how pre-existing files in the destination are handled. The commit phase ordering becomes: validate dest → download/transfer (skipping validated) → clean dest.

**Tech Stack:** Python 3.10+, pywebview, HTML/CSS/JS (single-file UI)

---

### Task 1: Update OutputConfig and AdvancedConfig dataclasses

**Files:**
- Modify: `retro_refiner/config.py:247-276`

**Step 1: Update the config dataclasses**

In `OutputConfig`, rename `transfer_mode` to `local_file_action` (keep `transfer_mode` as a legacy alias in `from_dict`). Add two new destination options:

```python
@dataclass
class OutputConfig:
    """Output and transfer options."""
    local_file_action: str = 'copy'
    flat: bool = False
    playlists: bool = False
    gamelist: bool = False
    retroarch_playlists: Optional[str] = None
    prefer_source: Optional[str] = None
    print_roms: bool = False
    validate_destination: bool = True
    clean_destination: bool = False
    crc_validation: bool = False
```

Update `from_dict()` to accept legacy `transfer_mode` key and map it to `local_file_action`. The `delete-dupes` value should map to `remove`.

**Step 2: Update Config.to_dict() if it exists**

Ensure serialization uses the new field name `local_file_action`. Keep backward compat in deserialization.

**Step 3: Run existing config tests to verify nothing breaks**

Run: `python tests/test_v2_config.py`
Expected: All 65 tests pass (some may need updating for the renamed field)

**Step 4: Fix any broken tests**

Update test assertions that reference `transfer_mode` to use `local_file_action`.

**Step 5: Commit**

```bash
git add retro_refiner/config.py tests/test_v2_config.py
git commit -m "refactor: rename transfer_mode to local_file_action, add destination options"
```

---

### Task 2: Update transfer.py — add destination validation and cleaning

**Files:**
- Modify: `retro_refiner/transfer.py:1-66`

**Step 1: Write the validate_destination function**

Add a function that scans the destination for existing files and checks them against expected sizes. Returns a set of filenames that are valid (should be skipped) and a set that are invalid (should be replaced).

```python
def validate_destination(dest_dir: Path, system: Optional[str],
                         flat: bool, expected_files: Dict[str, int],
                         crc_check: bool = False,
                         crc_data: Optional[Dict[str, str]] = None,
                         on_progress: Optional[Callable] = None
                         ) -> Dict[str, str]:
    """Validate files already in destination directory.

    Args:
        dest_dir: Destination directory.
        system: System code for subdirectory.
        flat: If True, files are directly in dest_dir.
        expected_files: Dict of filename -> expected_size.
        crc_check: If True, also verify CRC32 (requires crc_data).
        crc_data: Dict of filename -> expected_crc32 hex string.
        on_progress: Optional progress callback.

    Returns:
        Dict of filename -> status ('valid', 'invalid', 'missing').
    """
    target_dir = dest_dir if (flat or not system) else dest_dir / system
    result = {}
    for filename, expected_size in expected_files.items():
        filepath = target_dir / filename
        if not filepath.exists():
            result[filename] = 'missing'
            continue
        actual_size = filepath.stat().st_size
        if actual_size != expected_size:
            result[filename] = 'invalid'
            continue
        if crc_check and crc_data and filename in crc_data:
            from retro_refiner.dat import calculate_crc32
            actual_crc = calculate_crc32(filepath)
            if actual_crc != crc_data[filename]:
                result[filename] = 'invalid'
                continue
        result[filename] = 'valid'
    return result
```

**Step 2: Write the clean_destination function**

Add a function that removes files from the destination system directory that aren't in the expected set.

```python
def clean_destination(dest_dir: Path, system: Optional[str],
                      flat: bool, keep_files: set,
                      on_progress: Optional[Callable] = None
                      ) -> Dict[str, int]:
    """Remove files from destination that aren't in the keep set.

    Args:
        dest_dir: Destination directory.
        system: System code for subdirectory.
        flat: If True, files are directly in dest_dir.
        keep_files: Set of filenames to keep.
        on_progress: Optional progress callback.

    Returns:
        Dict with 'removed' and 'errors' counts.
    """
    target_dir = dest_dir if (flat or not system) else dest_dir / system
    stats = {'removed': 0, 'errors': 0}
    if not target_dir.exists():
        return stats
    for filepath in target_dir.iterdir():
        if filepath.is_file() and filepath.name not in keep_files:
            try:
                filepath.unlink()
                stats['removed'] += 1
            except OSError:
                stats['errors'] += 1
    return stats
```

**Step 3: Update transfer_files to support 'remove' mode**

The `delete-dupes` / `remove` mode is currently not implemented in `transfer_files`. Add explicit handling:

```python
elif mode == 'remove':
    src.unlink()
    stats['transferred'] += 1
```

Note: For `remove` mode, the function deletes source files that were NOT selected (the excluded ones). This is handled at the call site in api.py, not in transfer_files itself. Actually — review how `delete-dupes` currently works in api.py. If it's handled differently, preserve that logic. The `transfer_files` function may not need a `remove` mode at all if deletion is handled upstream.

**Step 4: Run transfer tests**

Run: `python tests/test_selection.py`
Expected: All 300 tests pass

**Step 5: Commit**

```bash
git add retro_refiner/transfer.py
git commit -m "feat: add validate_destination and clean_destination functions"
```

---

### Task 3: Update api.py — refactor commit phase

**Files:**
- Modify: `retro_refiner/ui/api.py:384-460`

This is the core change. The commit phase in `_do_run()` currently:
1. Builds download list → downloads to cache → transfers cache to dest
2. Applies `transfer_mode` uniformly to all files

New flow:
1. For each system, separate selected items into remote URLs and local files
2. **Validate destination** (if enabled): build skip list of files already valid in dest
3. **Remote files**: download directly to `dest_dir/system/` (not cache), using temp file + rename. Skip files that validated OK.
4. **Local files**: apply `local_file_action` (copy/move/hardlink/symlink). Skip files that validated OK. For `remove` mode, delete excluded local files from source (existing behavior, no dest needed).
5. **Clean destination** (if enabled): remove files not in the final selected set, scoped to processed systems only.

**Step 1: Refactor the per-system commit loop**

Extract the current download+transfer block (lines 394-460) into a new method `_commit_system()` that handles a single system. This method should:

```python
def _commit_system(self, system, config, dest_dir, cache_dir):
    """Commit results for a single system."""
    result = self._last_results.get(system, {})
    selected_urls = result.get('selected_urls', [])
    local_files = result.get('local_files', [])

    # Apply manual picker overrides
    manual = self._manual_selections.get(system, {})
    if manual:
        selected_urls = [u for u in selected_urls
                         if manual.get(self._url_to_filename(u), True)]
        local_files = [f for f in local_files
                       if manual.get(Path(f).name, True)]

    if not selected_urls and not local_files:
        return

    flat = config.output.flat
    target_dir = dest_dir if flat else dest_dir / system
    target_dir.mkdir(parents=True, exist_ok=True)

    # Build expected file set with sizes
    expected = {}
    sizes = result.get('sizes', {})
    for url in selected_urls:
        fn = self._url_to_filename(url)
        expected[fn] = sizes.get(url, 0)
    for filepath in local_files:
        p = Path(filepath)
        if p.exists():
            expected[p.name] = p.stat().st_size

    # Phase 1: Validate destination
    skip_files = set()
    if config.output.validate_destination and config.output.local_file_action != 'remove':
        from retro_refiner.transfer import validate_destination
        validation = validate_destination(
            dest_dir, system, flat, expected,
            crc_check=config.output.crc_validation)
        skip_files = {fn for fn, status in validation.items() if status == 'valid'}
        invalid_files = {fn for fn, status in validation.items() if status == 'invalid'}
        if skip_files:
            self._push_event('log', {
                'text': f'  {self._display_name(system)}: {len(skip_files)} files already in destination, skipping\n',
            })
        # Delete invalid files so they get re-downloaded/copied
        for fn in invalid_files:
            (target_dir / fn).unlink(missing_ok=True)

    # Phase 2: Download remote files directly to destination
    downloads = []
    for url in selected_urls:
        fn = self._url_to_filename(url)
        if fn in skip_files:
            continue
        dest_path = target_dir / fn
        # Use .tmp suffix for crash safety — renamed on completion
        tmp_path = target_dir / (fn + '.rrdownload')
        downloads.append((url, tmp_path, dest_path))

    if downloads:
        self._push_event('log', {
            'text': f'  {self._display_name(system)}: downloading {len(downloads)} files...\n',
        })
        self._download_to_destination(downloads, config.network.parallel, system)

    # Phase 3: Transfer local files
    if local_files and config.output.local_file_action != 'remove':
        from retro_refiner.transfer import transfer_files
        files_to_transfer = [Path(f) for f in local_files
                             if Path(f).name not in skip_files]
        if files_to_transfer:
            stats = transfer_files(
                files_to_transfer, dest_dir, system=system,
                mode=config.output.local_file_action,
                flat=flat)
            self._push_event('log', {
                'text': f'  {self._display_name(system)}: transferred {stats["transferred"]}, '
                        f'skipped {stats["skipped"]}, errors {stats["errors"]}\n',
            })

    # Phase 4: Clean destination
    if config.output.clean_destination and config.output.local_file_action != 'remove':
        from retro_refiner.transfer import clean_destination
        keep = set(expected.keys())
        clean_stats = clean_destination(dest_dir, system, flat, keep)
        if clean_stats['removed']:
            self._push_event('log', {
                'text': f'  {self._display_name(system)}: cleaned {clean_stats["removed"]} files from destination\n',
            })
```

**Step 2: Write `_download_to_destination` method**

This replaces `_download_batch`. Downloads go to `.rrdownload` temp files, renamed to final name on completion. Reuses existing aria2c/curl/urllib logic but targets destination instead of cache.

```python
def _download_to_destination(self, downloads, parallel, system):
    """Download files to destination with temp file safety.

    Args:
        downloads: List of (url, tmp_path, final_path) tuples.
        parallel: Max parallel downloads.
        system: System code for logging.
    """
    # Build download list as (url, tmp_path) for the batch downloader
    batch = [(url, tmp_path) for url, tmp_path, _ in downloads]
    self._download_batch(batch, parallel, system)

    # Rename completed downloads from .rrdownload to final name
    for url, tmp_path, final_path in downloads:
        if tmp_path.exists():
            tmp_path.rename(final_path)
```

**Step 3: Update the main commit block in `_do_run`**

Replace the current per-system download+transfer loop (lines 394-460) with calls to `_commit_system()`:

```python
if commit and self._running:
    dest_dir = (Path(config.destination) if config.destination
                else get_runtime_path() / 'refined')
    dest_dir.mkdir(parents=True, exist_ok=True)

    for system in sorted(all_systems):
        if not self._running:
            break
        self._commit_system(system, config, dest_dir, cache_dir)
```

**Step 4: Handle the 'remove' local file action**

The `remove` / `delete-dupes` mode deletes excluded files from source, not transferring anything. This needs separate handling — it should delete files from local sources that were NOT selected. Review current behavior and preserve it. The destination is not involved.

**Step 5: Add `_url_to_filename` helper**

Extract the repeated URL-to-filename logic into a helper:

```python
def _url_to_filename(self, url):
    """Extract filename from URL."""
    return urllib.parse.unquote(
        url.split('?')[0].split('#')[0].split('/')[-1])
```

**Step 6: Run all tests**

Run: `python tests/test_selection.py && python tests/test_v2_modules.py && python tests/test_v2_config.py && python tests/test_v2_cli.py && python tests/test_v2_integration.py`
Expected: All tests pass

**Step 7: Commit**

```bash
git add retro_refiner/ui/api.py
git commit -m "refactor: download directly to destination, add validation and cleaning phases"
```

---

### Task 4: Update the UI — rename label, add destination options

**Files:**
- Modify: `retro_refiner/ui/assets/index.html`

**Step 1: Rename "File action" to "Local file action"**

Change line 631:
```html
<div class="field-label">Local file action</div>
```

**Step 2: Add destination options**

Add checkboxes for "Validate existing" and "Clean destination" near the destination path picker (inside `dest-group`, after the path picker, before the local file action dropdown). Add a "CRC validation" checkbox that's only visible when "Validate existing" is checked.

```html
<div id="dest-group">
  <div class="field-label">Destination</div>
  <input type="hidden" id="dest-path">
  <div class="path-picker" onclick="browsePathPicker('dest-path', 'dest-path-display')" title="Where filtered ROMs will be transferred">
    <span class="path-icon">&#x1F4C1;</span>
    <span class="path-text" id="dest-path-display">Select destination folder...</span>
    <span class="path-clear" aria-label="Clear destination" onclick="event.stopPropagation(); clearPathPicker('dest-path', 'dest-path-display', 'Select destination folder...')">&#xD7;</span>
  </div>
  <div class="dest-options" style="margin-top:6px">
    <label title="Check files already in the destination by size. Valid files are skipped; partial or corrupted files are re-downloaded or re-copied.">
      <input type="checkbox" id="opt-validate-dest" checked> Validate existing files
    </label>
    <label title="Use CRC32 checksums (from DAT files) for stricter validation. Slower but catches corrupted files that match the expected size." style="margin-left:16px" id="opt-crc-label">
      <input type="checkbox" id="opt-crc-validation"> CRC
    </label>
    <br>
    <label title="After processing, remove files from the destination that aren't in the selected set. Only affects systems being processed.">
      <input type="checkbox" id="opt-clean-dest"> Clean destination
    </label>
  </div>
</div>
```

**Step 3: Show/hide CRC option based on validate checkbox**

```javascript
document.getElementById('opt-validate-dest').addEventListener('change', function() {
  document.getElementById('opt-crc-label').style.display = this.checked ? '' : 'none';
});
```

**Step 4: Update `toggleDestForTransferMode()`**

The destination options should also be hidden/disabled when local file action is `remove`:

```javascript
function toggleDestForTransferMode() {
  var mode = document.getElementById('opt-transfer').value;
  var destGroup = document.getElementById('dest-group');
  if (mode === 'delete-dupes') {
    destGroup.style.opacity = '0.35';
    destGroup.style.pointerEvents = 'none';
  } else {
    destGroup.style.opacity = '1';
    destGroup.style.pointerEvents = '';
  }
}
```

(This already works since the dest options are inside `dest-group`.)

**Step 5: Update `gatherUiState()` to include new fields**

```javascript
validate_destination: document.getElementById('opt-validate-dest').checked,
clean_destination: document.getElementById('opt-clean-dest').checked,
crc_validation: document.getElementById('opt-crc-validation').checked,
local_file_action: document.getElementById('opt-transfer').value,
```

Note: Keep emitting `transfer_mode` alongside `local_file_action` for any backward compat, or update all references.

**Step 6: Update `restoreUiState()` to restore new fields**

```javascript
document.getElementById('opt-validate-dest').checked = out.validate_destination !== false;
document.getElementById('opt-clean-dest').checked = !!out.clean_destination;
document.getElementById('opt-crc-validation').checked = !!out.crc_validation;
document.getElementById('opt-transfer').value = out.local_file_action || out.transfer_mode || 'copy';
```

**Step 7: Update `update_config_from_ui()` in api.py**

Map the new UI fields to the config dataclass:

```python
out.validate_destination = ui.get('validate_destination', True)
out.clean_destination = ui.get('clean_destination', False)
out.crc_validation = ui.get('crc_validation', False)
out.local_file_action = ui.get('local_file_action', ui.get('transfer_mode', 'copy'))
```

**Step 8: Commit**

```bash
git add retro_refiner/ui/assets/index.html retro_refiner/ui/api.py
git commit -m "feat: rename to Local file action, add Validate existing and Clean destination options"
```

---

### Task 5: Update CLI (headless) path

**Files:**
- Modify: `retro_refiner/cli.py`

**Step 1: Review cli.py for transfer_mode references**

Search for `transfer_mode` and update to `local_file_action`. Ensure the CLI commit flow also:
- Downloads directly to destination (not cache→copy)
- Respects `validate_destination` and `clean_destination` config fields
- Uses temp file + rename for downloads

**Step 2: Run CLI tests**

Run: `python tests/test_v2_cli.py`
Expected: All 36 tests pass

**Step 3: Commit**

```bash
git add retro_refiner/cli.py
git commit -m "refactor: update CLI to use local_file_action and destination-direct downloads"
```

---

### Task 6: Update CLAUDE.md and default config

**Files:**
- Modify: `CLAUDE.md`
- Modify: `retro-refiner.yaml` (if it references transfer_mode)

**Step 1: Update CLAUDE.md**

- Update OutputConfig docs to show `local_file_action` instead of `transfer_mode`
- Add `validate_destination`, `clean_destination`, `crc_validation` fields
- Update the "Key Data Flow" section to describe the new commit phases
- Update the sidebar structure description

**Step 2: Update default config template**

If `retro-refiner.yaml` references `transfer_mode`, rename to `local_file_action`.

**Step 3: Commit**

```bash
git add CLAUDE.md retro-refiner.yaml
git commit -m "docs: update CLAUDE.md for destination refactor"
```

---

### Task 7: Write tests for new functionality

**Files:**
- Modify: `tests/test_selection.py` or create: `tests/test_v2_transfer.py`

**Step 1: Write tests for `validate_destination`**

Test cases:
- File exists with correct size → `'valid'`
- File exists with wrong size → `'invalid'`
- File doesn't exist → `'missing'`
- CRC check enabled, correct CRC → `'valid'`
- CRC check enabled, wrong CRC → `'invalid'`
- Empty expected_files dict → empty result

**Step 2: Write tests for `clean_destination`**

Test cases:
- Remove files not in keep set
- Keep files that are in keep set
- Empty directory → no errors
- Non-existent directory → returns zeros

**Step 3: Write tests for backward compat**

- Config with `transfer_mode` key loads as `local_file_action`
- Config with `delete-dupes` maps correctly

**Step 4: Run all tests**

Run: `python tests/test_selection.py && python tests/test_v2_modules.py && python tests/test_v2_config.py && python tests/test_v2_cli.py && python tests/test_v2_integration.py && python tests/test_v2_paths.py && python tests/test_v2_systems.py`
Expected: All 508+ tests pass

**Step 5: Commit**

```bash
git add tests/
git commit -m "test: add tests for destination validation and cleaning"
```

---

### Task 8: Lint and final verification

**Step 1: Run pylint**

Run: `python -m pylint retro_refiner/`
Expected: Score 10.00/10

**Step 2: Fix any lint issues**

**Step 3: Run all tests one final time**

Run all test files listed above.
Expected: All pass

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve lint warnings from destination refactor"
```

---

## Key Design Decisions

1. **Default changed from `move` to `copy`** — `move` was a workaround for cache duplication. With direct-to-destination downloads, `copy` is the safer default for local files.

2. **`.rrdownload` temp file extension** — distinctive enough to not collide with ROM files. Easy to identify and clean up after crashes.

3. **Validate destination defaults to ON** — this is the common case (resume a partial run). Users who want a fresh start can uncheck it.

4. **Clean destination defaults to OFF** — destructive action should be opt-in.

5. **Clean scoped to processed systems** — prevents accidentally wiping unrelated system folders in the destination.

6. **Size-based validation as default** — fast, catches partial downloads (the most common failure). CRC is opt-in for users who want stricter checking.
