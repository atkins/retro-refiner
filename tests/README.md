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

---

## test_network_sources.py

Functional tests for network source operations. Tests real network scanning against Myrient archives.

### What it tests

- **No-Intro sources**: GBA scanning, filtering, dry-run mode
- **No-Intro + T-En combined**: Translation source integration
- **MAME CHDs**: Parallel game folder scanning, category filtering
- **FBNeo arcade**: Direct arcade ROM scanning
- **FBNeo recursive**: Multi-system scanning with `-r` flag
- **TeknoParrot**: Modern arcade ROM scanning, platform filtering
- **Redump sources**: PlayStation, Saturn CD-ROM scanning
- **Cache operations**: Cache directory configuration, `--clean` flag
- **Parallel scanning**: `--scan-workers`, `-r/--recursive`, `--max-depth`
- **Error handling**: Invalid URLs, 404 responses
- **Filtering**: Region priority, include/exclude patterns with network sources
- **Multi-source**: Combining sources, `--prefer-source`

### Usage

```bash
# Run all tests (takes several minutes)
python tests/test_network_sources.py

# Run quick test suite (5 key tests)
python tests/test_network_sources.py --quick

# Run specific test
python tests/test_network_sources.py --test mame
python tests/test_network_sources.py --test teknoparrot
python tests/test_network_sources.py --test fbneo
python tests/test_network_sources.py --test redump
```

### Available tests

| Test | Description |
|------|-------------|
| `nointro` | No-Intro GBA source scan |
| `ten` | No-Intro + T-En combined |
| `mame` | MAME CHDs with parallel scanning |
| `fbneo` | FBNeo arcade |
| `fbneo_recursive` | FBNeo all systems with `-r` |
| `teknoparrot` | TeknoParrot scan |
| `teknoparrot_platform` | TeknoParrot platform filter |
| `redump` | Redump PlayStation |
| `redump_saturn` | Redump Saturn |
| `cache` | Cache directory |
| `clean` | Cache clearing `--clean` |
| `workers` | `--scan-workers` option |
| `recursive` | `-r` recursive flag |
| `maxdepth` | `--max-depth` option |
| `invalid_url` | Invalid URL handling |
| `404` | 404 error handling |
| `region` | Region filter with network |
| `include_exclude` | Include/exclude patterns |
| `multi_source` | Multiple network sources |
| `prefer_source` | `--prefer-source` option |

### Requirements

- Network connection to Myrient (myrient.erista.me)
- Tests run in dry-run mode (no files downloaded)
- Typical run time: 5-15 minutes for full suite

### Exit codes

- `0` - All tests passed
- `1` - One or more tests failed
