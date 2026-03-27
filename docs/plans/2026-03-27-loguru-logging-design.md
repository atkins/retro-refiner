# Loguru Logging Design

## Goal

Replace the manual log buffer / file writing system with loguru. Create two distinct log channels: a visual log (GUI events, unchanged) and a system log (always-on debug file via loguru).

## Architecture

### Two Log Channels

1. **Visual log** — `_push_event('log', {...})` calls in api.py push messages to the GUI. These are user-facing, styled with CSS classes (log-error, log-warning, log-success). No change to this system.

2. **System log** — loguru writes to `retro-refiner.log` next to the executable. Always on, no config needed. Captures DEBUG+ level messages from all modules. Auto-rotates at 10MB, keeps 3 backups.

### Log File Configuration

- **Path**: `get_runtime_path() / 'retro-refiner.log'`
- **Rotation**: 10 MB
- **Retention**: 3 files
- **Format**: `{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {module}:{function}:{line} | {message}`
- **Level**: DEBUG

## What Changes

### New: `retro_refiner/log.py`

Configures loguru on import. All other modules import `logger` from here:

```python
from loguru import logger
from retro_refiner.paths import get_runtime_path

logger.remove()  # remove default stderr handler
logger.add(
    get_runtime_path() / 'retro-refiner.log',
    level='DEBUG',
    rotation='10 MB',
    retention=3,
    format='{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {module}:{function}:{line} | {message}',
)
```

### Remove: `_log_buffer` system in api.py

- Delete `_log_buffer` field from `Api.__init__`
- Delete buffer accumulation in `_push_event`
- Delete `_write_run_logs()` method (~170 lines)
- Delete `_write_run_logs` call in `_do_run`

### Remove: `log_dir` config and GUI

- Remove `log_dir` field from `AdvancedConfig` in config.py
- Remove log directory path picker from index.html (opt-log-dir)
- Remove `log_dir` from `gatherUiState()` and `restoreUiState()` in JS
- Remove `log_dir` from `update_config_from_ui()` in api.py

### Replace: `print(file=sys.stderr)` calls (12 occurrences)

All stderr error/warning prints become loguru calls:

| File | Current | Replacement |
|------|---------|-------------|
| `dat.py` | `print(..., file=sys.stderr)` | `logger.warning(...)` |
| `scanner.py` | `_log_error(msg)` | `logger.error(msg)` |
| `dedup.py` | `print(..., file=sys.stderr)` | `logger.warning(...)` |
| `teknoparrot.py` | `print(..., file=sys.stderr)` | `logger.warning(...)` |
| `cli.py` | `print(..., file=sys.stderr)` | `logger.error(...)` |

### Add: Debug logging throughout modules

Add `logger.debug()` calls at key points for development/testing:
- Network: URL fetches, redirect resolution, response status
- Scanner: system detection, directory traversal, ROM discovery
- Filter: title normalization, region selection, exclusion reasons
- DAT: file downloads, parse results, CRC lookups
- API: run start/stop, phase transitions, config snapshots

### Keep unchanged

- All 36 `_push_event('log', ...)` calls in api.py (GUI visual log)
- All 35 `print()` calls in cli.py (intentional CLI output)
- All `_push_event` calls for structured events (system-complete, fanfare, etc.)

## Files Changed

| File | Change |
|------|--------|
| `retro_refiner/log.py` | NEW — loguru configuration |
| `retro_refiner/ui/api.py` | Remove _log_buffer, _write_run_logs, log_dir references. Add logger.debug at key points |
| `retro_refiner/config.py` | Remove log_dir from AdvancedConfig |
| `retro_refiner/ui/assets/index.html` | Remove log directory path picker and JS references |
| `retro_refiner/dat.py` | Replace stderr prints with logger.warning |
| `retro_refiner/scanner.py` | Replace _log_error with logger.error, add logger.debug |
| `retro_refiner/dedup.py` | Replace stderr prints with logger.warning |
| `retro_refiner/teknoparrot.py` | Replace stderr prints with logger.warning |
| `retro_refiner/cli.py` | Replace stderr prints with logger.error |
| `retro_refiner/network.py` | Add logger.debug for fetches |
| `retro_refiner/filter.py` | Add logger.debug for filtering decisions |
| `tests/test_updater.py` | May need minor updates |

## Dependencies

- **Add**: `loguru`

## Testing

- Existing tests continue to work (visual log unchanged)
- loguru's `logger.add(sink)` makes test log capture easy:
  ```python
  messages = []
  logger.add(lambda m: messages.append(str(m)), level="DEBUG")
  # run operation
  assert any("Filtering" in m for m in messages)
  ```
- Future: functional tests can assert on log file contents for automated UI testing
