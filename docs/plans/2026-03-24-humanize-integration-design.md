# humanize Integration Design

## Goal

Replace the custom `format_size()` function with the `humanize` library's `naturalsize()` for human-readable byte formatting throughout the codebase.

## Motivation

- **Correctness**: Uses proper binary units (MiB/GiB) instead of ambiguous MB/GB
- **Simplicity**: Deletes 11 lines of custom formatting code
- **Consistency**: Battle-tested library with locale support and edge-case handling

## What Changes

### Replace: `format_size()` in `network.py`

**Current** (lines 45-55):
```python
def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes < 1024 ** 4:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    return f"{size_bytes / (1024 ** 4):.2f} TB"
```

**Replacement:**
```python
def format_size(size_bytes: int) -> str:
    """Format a size in bytes to a human-readable string."""
    import humanize  # pylint: disable=import-outside-toplevel
    return humanize.naturalsize(size_bytes, binary=True)
```

The function signature and name stay the same — all 25+ call sites across 6 files continue to work without changes.

### Output format change

| Bytes | Before | After |
|-------|--------|-------|
| 500 | `500 Bytes` | `500 Bytes` |
| 51200 | `50.0 KB` | `50.0 KiB` |
| 558891008 | `532.9 MB` | `533.0 MiB` |
| 1288490189 | `1.20 GB` | `1.2 GiB` |
| 1099511627776 | `1.00 TB` | `1.0 TiB` |

Units change from KB/MB/GB/TB to KiB/MiB/GiB/TiB. Decimal precision may vary slightly (humanize uses its own rounding).

### What stays custom

- `_elapsed_str()` in `api.py` — compact `"2m 03s"` format for progress bars
- `_format_time()` in `scanner.py` — compact `"1:23"` format for progress bars
- `_eta_str()` in `api.py` — rate computation + `"~Xm Ys left"` format
- `parse_size_string()` / `_parse_size_string()` — input parsing, not formatting

### Files Changed

| File | Change |
|------|--------|
| `retro_refiner/network.py` | Replace `format_size()` body with humanize call |
| `tests/test_network.py` | Update format_size assertions (KB→KiB, MB→MiB, etc.) |
| `tests/test_cli.py` | Update format_size assertions |
| `pyproject.toml` | No change needed (no [project.dependencies] section) |

### Test Updates

Tests that assert exact format_size output strings need updating:
- `test_format_size` parametrized tests in `test_network.py` and `test_cli.py`
- `test_format_size_5gb`, `test_format_size_negative` in `test_network.py`
- `test_format_size_just_under_1mb` in `test_cli.py`
- Any tests that check size strings in HTML parsing results

### Dependencies

- **Add**: `humanize` (pip install humanize)
- **No removals**
