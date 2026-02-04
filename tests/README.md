# Tests

## test_selection.py

Unit and integration tests for Retro-Refiner's core functionality.

### What it tests

- ROM filename parsing (regions, revisions, languages, tags)
- Title normalization and Japan→English mappings
- ROM selection logic (best version picking)
- Config file handling (YAML loading, defaults)
- URL parsing and normalization
- HTML parsing for directory listings
- Pattern matching (include/exclude filters)
- Network ROM filtering
- System detection (folder aliases, extensions)
- Playlist generation (M3U, gamelist.xml)

### Usage

```bash
# Run all tests
python tests/test_selection.py

# Run with series selection tests (requires local ROM collection)
python tests/test_selection.py --series
```

### Exit codes

- `0` - All tests passed
- `1` - One or more tests failed

---

## test_bandwidth.py

Benchmarks download performance with different aria2c settings to find optimal configuration for your connection.

### What it tests

Tests combinations of `--parallel` (concurrent downloads) and `--connections` (connections per file) settings against real ROM archives.

**Sources:**
- Myrient (no auth required)
- Archive.org (requires credentials)

**File sizes:**
- Small: Game Boy ROMs (~32KB-1MB)
- Large: PlayStation 2 ISOs (~1-4GB)

### Usage

```bash
# Quick test against Myrient (4 configurations)
python tests/test_bandwidth.py --site myrient --quick

# Full test against Myrient (25 configurations)
python tests/test_bandwidth.py --site myrient

# Test only large files
python tests/test_bandwidth.py --site myrient --size large

# Custom duration per test (default: 30s)
python tests/test_bandwidth.py --site myrient --duration 60

# Test both sites (requires Archive.org credentials)
python tests/test_bandwidth.py --site both
```

### Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--site` | `myrient`, `archiveorg`, `both` | `both` | Which site(s) to test |
| `--size` | `small`, `large`, `both` | `both` | Which file sizes to test |
| `--quick` | flag | off | Run only 4 key configurations |
| `--duration` | seconds | 30 | Duration per test |

### Archive.org credentials

Required for Archive.org tests:

```bash
export IA_ACCESS_KEY=your_access_key
export IA_SECRET_KEY=your_secret_key
```

Get credentials at: https://archive.org/account/s3.php

### Output

Reports download speed for each configuration and recommends optimal settings:

```
BEST: --parallel 8 --connections 8 (12.5 MB/s)
```
