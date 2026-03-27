# Loguru Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual log buffer / file writing system with loguru. Two channels: visual log (GUI events, unchanged) and system log (always-on debug file).

**Architecture:** New `log.py` module configures loguru with a rotating file sink. All modules import `logger` from there. Remove `_log_buffer`, `_write_run_logs`, and `log_dir` config. Replace stderr prints with loguru calls. Add debug logging at key points.

**Tech Stack:** loguru, existing pywebview event system

---

### Task 1: Install loguru and create `log.py`

**Files:**
- Create: `retro_refiner/log.py`

- [ ] **Step 1: Install loguru**

```bash
pip install loguru
```

- [ ] **Step 2: Create `retro_refiner/log.py`**

```python
"""Logging configuration for Retro-Refiner.

Two log channels:
- Visual log: _push_event('log', ...) to the GUI (unchanged)
- System log: loguru file sink for debug/development (this module)

All modules should import logger from here:
    from retro_refiner.log import logger
"""
from loguru import logger

from retro_refiner.paths import get_runtime_path

# Remove loguru's default stderr handler
logger.remove()

# Always-on file sink — debug level, rotating, next to the executable
logger.add(
    get_runtime_path() / 'retro-refiner.log',
    level='DEBUG',
    rotation='10 MB',
    retention=3,
    format='{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {module}:{function}:{line} | {message}',
    encoding='utf-8',
)
```

- [ ] **Step 3: Add `retro-refiner.log` to `.gitignore`**

Add this line to `.gitignore` under the existing "Retro-Refiner generated data" section:

```
retro-refiner.log
retro-refiner.log.*
```

- [ ] **Step 4: Add loguru to `pyproject.toml` dependencies**

Add `"loguru"` to the `dependencies` list in `pyproject.toml`.

- [ ] **Step 5: Verify import works**

```bash
python -c "from retro_refiner.log import logger; logger.info('test'); print('OK')"
```

Expected: prints "OK" and creates `retro-refiner.log` with a test entry.

- [ ] **Step 6: Commit**

```bash
git add retro_refiner/log.py .gitignore pyproject.toml
git commit -m "feat: add loguru logging with rotating file sink"
```

---

### Task 2: Remove `_log_buffer`, `_write_run_logs`, and `log_dir`

**Files:**
- Modify: `retro_refiner/ui/api.py`
- Modify: `retro_refiner/config.py`
- Modify: `retro_refiner/filter.py`
- Modify: `retro_refiner/ui/assets/index.html`

- [ ] **Step 1: Remove `log_dir` from `AdvancedConfig` in `config.py`**

In `retro_refiner/config.py`, find the `AdvancedConfig` dataclass and remove the `log_dir` field:

```python
# DELETE this line:
    log_dir: Optional[str] = None
```

- [ ] **Step 2: Remove `log_dir` from `filter.py`**

In `retro_refiner/filter.py`, the `filter_roms_from_files` function has a `log_dir` parameter. Remove it and the log file writing block that uses it (the block starting with `if log_dir:` near line 900).

- [ ] **Step 3: Remove `_log_buffer` and `_write_run_logs` from `api.py`**

In `retro_refiner/ui/api.py`:

1. In `__init__` (line 49), delete: `self._log_buffer = []`

2. In `_do_run` (line 522), delete: `self._log_buffer = []`

3. In `_do_run`, delete the `_write_run_logs` call block (around lines 740-748):
```python
            # DELETE this block:
            if config.advanced.log_dir and self._running:
                self._write_run_logs(
                    config, all_systems, all_sizes,
                    total_selected, total_excluded, total_size,
                    total_source_size, run_start,
                    commit)
```

4. Delete the entire `_write_run_logs` method (starts around line 1391, ~170 lines).

5. In `_push_event` (around lines 2368-2372), delete the log buffer accumulation:
```python
            # DELETE this block:
            if (event_type == 'log' and self._log_buffer is not None
                    and self._config.advanced.log_dir):
                text = data.get('text', '')
                if text:
                    self._log_buffer.append(text)
```

6. In `update_config_from_ui` (line 453), delete: `adv.log_dir = ui.get('log_dir') or None`

7. In `_filter_system`, remove the `log_dir=config.advanced.log_dir` argument from the `filter_roms_from_files` call (around line 1182).

- [ ] **Step 4: Remove log directory picker from `index.html`**

Delete these lines (around 902-908):
```html
        <div class="field-label" style="font-size:9px;color:var(--text-muted);margin-top:4px;letter-spacing:0">Log directory</div>
        <input type="hidden" id="opt-log-dir">
        <div class="path-picker" onclick="browsePathPicker('opt-log-dir', 'opt-log-dir-display')" title="Directory for filter log files">
          <span class="path-icon">&#x1F4C1;</span>
          <span class="path-text" id="opt-log-dir-display">Select folder...</span>
          <span class="path-clear" aria-label="Clear log directory" onclick="event.stopPropagation(); clearPathPicker('opt-log-dir', 'opt-log-dir-display', 'Select folder...')">&#xD7;</span>
        </div>
```

In `restoreUiState` (around line 1528), delete:
```javascript
  if (adv.log_dir) setPathPicker('opt-log-dir', 'opt-log-dir-display', adv.log_dir);
```

In `gatherUiState` (around line 1640), delete:
```javascript
    log_dir: document.getElementById('opt-log-dir').value || '',
```

- [ ] **Step 5: Run tests and lint**

```bash
python -m pytest --ignore=tests/test_smoke.py -v --tb=short
python -m pylint retro_refiner/
```

Fix any test failures caused by removed fields (check test_config.py, test_api.py for log_dir references).

- [ ] **Step 6: Commit**

```bash
git add retro_refiner/ui/api.py retro_refiner/config.py retro_refiner/filter.py retro_refiner/ui/assets/index.html
git commit -m "refactor: remove _log_buffer, _write_run_logs, and log_dir config"
```

---

### Task 3: Replace stderr prints with loguru in all modules

**Files:**
- Modify: `retro_refiner/dat.py`
- Modify: `retro_refiner/scanner.py`
- Modify: `retro_refiner/dedup.py`
- Modify: `retro_refiner/cli.py`

- [ ] **Step 1: Replace stderr prints in `dat.py`**

Add import at top:
```python
from retro_refiner.log import logger
```

Replace line 246:
```python
# BEFORE:
print(f"ERROR: No DAT mapping for: {system}", file=sys.stderr)
# AFTER:
logger.warning("No DAT mapping for: {}", system)
```

Replace line 271:
```python
# BEFORE:
print(f"ERROR: Failed to download DAT for: {system}", file=sys.stderr)
# AFTER:
logger.warning("Failed to download DAT for: {}", system)
```

Check for any other `sys.stderr` usage in dat.py and replace similarly.

- [ ] **Step 2: Replace `_log_error` and stderr in `scanner.py`**

Add import at top:
```python
from retro_refiner.log import logger
```

Replace the `_log_error` function (lines 157-159):
```python
# BEFORE:
def _log_error(msg: str):
    """Write an error message to stderr."""
    print(msg, file=sys.stderr, flush=True)

# AFTER:
def _log_error(msg: str):
    """Log an error message."""
    logger.error(msg)
```

- [ ] **Step 3: Replace stderr prints in `dedup.py`**

Add import at top:
```python
from retro_refiner.log import logger
```

Replace line 28:
```python
# BEFORE:
print(f"WARNING: PC game list not found: {xml_path}", file=sys.stderr)
# AFTER:
logger.warning("PC game list not found: {}", xml_path)
```

Check for any other `sys.stderr` usage in dedup.py and replace similarly.

- [ ] **Step 4: Replace stderr prints in `cli.py`**

Add import at top:
```python
from retro_refiner.log import logger
```

Replace line 400:
```python
# BEFORE:
print("  WARNING: No ratings found in data", file=sys.stderr)
# AFTER:
logger.warning("No ratings found in data")
```

Check for any other `sys.stderr` usage in cli.py and replace similarly.

- [ ] **Step 5: Run tests and lint**

```bash
python -m pytest --ignore=tests/test_smoke.py -v --tb=short
python -m pylint retro_refiner/
```

- [ ] **Step 6: Commit**

```bash
git add retro_refiner/dat.py retro_refiner/scanner.py retro_refiner/dedup.py retro_refiner/cli.py
git commit -m "refactor: replace stderr prints with loguru across all modules"
```

---

### Task 4: Add debug logging at key points

**Files:**
- Modify: `retro_refiner/network.py`
- Modify: `retro_refiner/scanner.py`
- Modify: `retro_refiner/ui/api.py`
- Modify: `retro_refiner/dat.py`
- Modify: `retro_refiner/filter.py`

- [ ] **Step 1: Add debug logging to `network.py`**

Add import at top:
```python
from retro_refiner.log import logger
```

Add debug calls in key functions:

In `fetch_url` (after response received):
```python
logger.debug("Fetched {} ({} bytes)", url, len(response.content))
```

In `fetch_urls_parallel` (at start and end):
```python
logger.debug("Fetching {} URLs with {} workers", len(urls), actual_workers)
```

In `stream_download` (on entry):
```python
logger.debug("Downloading {} -> {}", url, dest_path)
```

In `validate_source` (on success/failure):
```python
logger.debug("Source validated: {}", url)
```

- [ ] **Step 2: Add debug logging to `scanner.py`**

Scanner already has the loguru import from Task 3. Add:

In `scan_network_source_urls` (on system detection):
```python
logger.debug("Detected system '{}' from URL: {}", url_system, base_url)
```

In `scan_network_source_urls` (on ROM discovery):
```python
logger.debug("Found {} ROMs in {}", len(rom_files_with_sizes), base_url)
```

- [ ] **Step 3: Add debug logging to `api.py`**

Add import at top:
```python
from retro_refiner.log import logger
```

In `_do_run` (at start):
```python
logger.info("Starting {} run", 'commit' if commit else 'preview')
```

In `_do_run` (at completion):
```python
logger.info("Run complete: {} selected across {} systems",
            total_selected, len(all_systems))
```

In `_filter_system` (per system):
```python
logger.debug("Filtering {}: {} URLs + {} local files",
             system, len(urls), len(local_files))
```

In `_download_batch` (at start):
```python
logger.debug("Downloading {} files for {} (parallel={})",
             len(downloads), system, parallel)
```

- [ ] **Step 4: Add debug logging to `dat.py`**

dat.py already has the loguru import from Task 3. Add:

In `download_libretro_dat` / `download_ten_dat` (on download start):
```python
logger.debug("Downloading DAT for system: {}", system)
```

In `load_all_system_dats` (on parse):
```python
logger.debug("Loaded {} DAT entries for {}", len(entries), system)
```

- [ ] **Step 5: Add debug logging to `filter.py`**

Add import at top:
```python
from retro_refiner.log import logger
```

In `filter_network_roms` (at start and result):
```python
logger.debug("Filtering {} ROMs for system '{}'", len(rom_urls), system)
logger.debug("Filter result: {} selected, {} excluded", len(result.selected), len(result.excluded))
```

- [ ] **Step 6: Run tests and lint**

```bash
python -m pytest --ignore=tests/test_smoke.py -v --tb=short
python -m pylint retro_refiner/
python -m ruff check retro_refiner/
```

- [ ] **Step 7: Commit**

```bash
git add retro_refiner/network.py retro_refiner/scanner.py retro_refiner/ui/api.py retro_refiner/dat.py retro_refiner/filter.py
git commit -m "feat: add debug logging throughout key modules"
```

---

### Task 5: Update CLAUDE.md, tests, and packaging

**Files:**
- Modify: `CLAUDE.md`
- Modify: `tests/test_modules.py`
- Modify: `retro_refiner/ui/app.py` (add log.py to hiddenimports if needed)

- [ ] **Step 1: Add `log` to module import test**

In `tests/test_modules.py`, add `"log"` to the `@pytest.mark.parametrize("module", [...])` list for `test_module_importable`.

- [ ] **Step 2: Update CLAUDE.md**

In the project structure section, add after `paths.py`:
```
    log.py            # Loguru configuration: rotating file sink for system/debug log
```

In the dependencies section, add `loguru` to the runtime list.

Update the test count to the current number.

Remove any references to `_write_run_logs`, `_log_buffer`, or `log_dir` from the `_do_run` phases section and elsewhere.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest --ignore=tests/test_smoke.py
python -m pylint retro_refiner/
python -m ruff check retro_refiner/
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md tests/test_modules.py
git commit -m "docs: update CLAUDE.md and tests for loguru logging"
```
